import json
import os
from datetime import datetime
from multiprocessing import Process
import fabric.api as fab

from pve import pve
from helpers import results

""" Configurations """

with open(os.path.dirname(__file__) + "/httperf_lb.json") as json_file:
    settings = json.load(json_file)

fab.env.warn_only = settings['env']['warn_only']
fab.env.hosts = settings['env']['hosts']
fab.env.roledefs = settings['env']['roledefs']
fab.env.user = settings['env']['user']
fab.env.password = settings['env']['password']
fab.env['vm'] = settings['env']['vm']
fab.env['analyst'] = settings['env']['analyst']

fab.env['httperf_lb'] = settings['httperf_lb']

""" Helper Functions """

vm_id_set = set()
server_vm_id_map = {}
for server_name, server_configs in fab.env['httperf_lb']['servers'].iteritems():
    for server_config in server_configs:
        vm_id = server_config['vm_id']
        vm_id_set |= {vm_id}
        server_vm_id_map[server_name + '_%s' % (vm_id,)] = '%s' % (vm_id,)
vm_id_list = list(vm_id_set)

""" 'httperf_lb' Commands """


@fab.roles('server')
def setup_scripts():
    scripts = list()
    script = \
        "sudo apt-get update; " \
        "sudo apt-get -y install libtool autoconf build-essential git " \
        "haproxy apache2 bridge-utils python-memcache python-matplotlib; " \
        "curl -sSL https://get.docker.com/ | sh; " \
        "git clone https://github.com/mshahbaz/httperf.git; " \
        "git clone https://github.com/mshahbaz/httperf-plot.git; " \
        "git clone https://github.com/mshahbaz/haproxy-dynamic-weight.git; " \
        "cd ~/httperf; autoreconf -i; ./configure; make; sudo make install; cd ~/; "
    scripts.append("echo '%s' > ~/setup_script.sh; " % (script,))
    scripts.append("sh ~/setup_script.sh; ")
    return scripts


@fab.roles('server')
def setup():
    pve.vm_generate_multi(fab.env['httperf_lb']['vm']['base_id'], "httperf-lb", False, setup_scripts(),
                          *vm_id_list)

    scripts = dict()
    for vm_id in vm_id_list:
        scripts[vm_id] = "sudo service docker stop; " \
                         "sudo service haproxy stop; " \
                         "sudo service apache2 stop; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def cleanup():
    pve.vm_destroy_multi(*vm_id_list)


@fab.roles('server')
def configure_web_servers():
    scripts = dict()
    for web_server in fab.env['httperf_lb']['servers']['web_server']:
        vm_id = web_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += "sudo sed -i 's/_HOSTNAME_/web_server_%s/g' ~/haproxy-dynamic-weight/request-lb-weight.py; " \
                          % (vm_id,)
        state_server_vm_id = fab.env['httperf_lb']['servers']['state_server'][
            web_server['state_server']['id']]['vm_id']
        state_server_timeout = web_server['state_server']['timeout']
        state_server_max_load = web_server['state_server']['max_load']
        scripts[vm_id] += "nohup python ~/haproxy-dynamic-weight/request-lb-weight.py %s%s:11211 %s %s " \
                          "> /dev/null 2> /dev/null < /dev/null & " \
                          % (fab.env['httperf_lb']['vm']['prefix_1'], state_server_vm_id,
                             state_server_timeout, state_server_max_load)
        scripts[vm_id] += "sudo sed -i 's/Listen 80/Listen 8080/g' /etc/apache2/ports.conf; " \
                          "sudo sed -i 's/VirtualHost \*:80/VirtualHost \*:8080/g' " \
                          "/etc/apache2/sites-enabled/000-default.conf; " \
                          "sudo service apache2 start; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_state_servers():
    scripts = dict()
    for state_server in fab.env['httperf_lb']['servers']['state_server']:
        vm_id = state_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += \
            "sudo service docker start; " \
            "sudo docker run --network=host --name state_server_%s -d memcached; " \
            % (vm_id,)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_lb_servers():
    scripts = dict()
    for lb_server in fab.env['httperf_lb']['servers']['lb_server']:
        vm_id = lb_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
        policy = lb_server['policy']
        scripts[vm_id] += \
            "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy; " \
            "sudo sed -i '8istats socket /var/run/haproxy.sock mode 666 level admin' /etc/haproxy/haproxy.cfg; " \
            "echo 'frontend web-serving' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    bind %s%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    default_backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo 'backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    balance %s' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id, policy)
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = fab.env['httperf_lb']['servers']['web_server'][web_server_id]['vm_id']
            scripts[vm_id] += \
                "echo '    server web_server_%s %s%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
                % (web_server_vm_id, fab.env['httperf_lb']['vm']['prefix_1'], web_server_vm_id)
        scripts[vm_id] += "sudo service haproxy start; "
        state_server_vm_id = fab.env['httperf_lb']['servers']['state_server'][
            lb_server['state_server']['id']]['vm_id']
        state_server_timeout = lb_server['state_server']['timeout']
        scripts[vm_id] += "sudo sed -i 's/\/etc\/haproxy\/haproxy.sock/\/var\/run\/haproxy.sock/g' " \
                          "~/haproxy-dynamic-weight/set-lb-weight.py; " \
                          "nohup python ~/haproxy-dynamic-weight/set-lb-weight.py %s%s:11211 %s " \
                          "> /dev/null 2> /dev/null < /dev/null & " \
                          % (fab.env['httperf_lb']['vm']['prefix_1'], state_server_vm_id, state_server_timeout)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_httperf_clients():
    scripts = dict()
    for httperf_client in fab.env['httperf_lb']['servers']['httperf_client']:
        vm_id = httperf_client['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
        num_conns = httperf_client['num-conns']
        num_calls = httperf_client['num-calls']
        rate = httperf_client['rate']
        ramp = httperf_client['ramp']
        iters = httperf_client['iters']
        timeout = httperf_client['timeout']
        lb_server_vm_id = fab.env['httperf_lb']['servers']['lb_server'][httperf_client['lb_server']]['vm_id']
        script = "cd ~/httperf-plot; " \
                 "python httperf-plot.py --server %s%s --port 8080 " \
                 "--hog --verbose --num-conns %s --num-calls %s --rate %s " \
                 "--ramp-up %s,%s --timeout %s " \
                 "--csv %s > %s; " \
                 "cd ~/; " \
                 % (fab.env['httperf_lb']['vm']['prefix_1'], lb_server_vm_id,
                    num_conns, num_calls, rate,
                    ramp, iters, timeout,
                    "httperf_client_%s.csv" % (vm_id,),
                    "httperf_client_%s.log" % (vm_id,))
        scripts[vm_id] += "echo '%s' > ~/httperf_script.sh; " % (script,)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure():
    proc_web = Process(target=configure_web_servers)
    proc_web.start()
    proc_state = Process(target=configure_state_servers)
    proc_state.start()
    proc_lb = Process(target=configure_lb_servers)
    proc_lb.start()
    proc_httperf = Process(target=configure_httperf_clients)
    proc_httperf.start()

    proc_web.join()
    proc_state.join()
    proc_lb.join()
    proc_httperf.join()


@fab.roles('server')
def httperf_client_is_ready():
    for httperf_client in fab.env['httperf_lb']['servers']['httperf_client']:
        vm_id = httperf_client['vm_id']
        if int(pve.vm_run(vm_id, 'netstat -t | wc -l')) > 100:
            fab.abort("too many TCP connections opened at client:%s" % (vm_id,))


@fab.roles('server')
def httperf_client_run():
    pve.vm_parallel_run({httperf_client['vm_id']: "sh ~/httperf_script.sh"
                         for httperf_client in fab.env['httperf_lb']['servers']['httperf_client']})


@fab.roles('server')
def post_httperf_client_run():
    datetime_str = str(datetime.now()).replace(':', '.').replace(' ', '.')
    fab.run("sshpass -p %s ssh %s 'mkdir %s/%s'; "
            % (fab.env.password, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
    for httperf_client in fab.env['httperf_lb']['servers']['httperf_client']:
        vm_id = httperf_client['vm_id']
        pve.vm_get(vm_id, "~/httperf-plot/httperf_client_%s.*" % (vm_id,), "/tmp/; ")
        fab.run("sshpass -p %s scp /tmp/httperf_client_%s.* %s:%s/%s/; "
                % (fab.env.password, vm_id, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
        pve.vm_run(vm_id, "rm -f ~/httperf-plot/httperf_client_%s.*; " % (vm_id,))
        fab.run("rm -f /tmp/httperf_client_%s.*; " % (vm_id,))


@fab.roles('server')
def start():
    httperf_client_is_ready()
    httperf_client_run()
    post_httperf_client_run()


@fab.roles('server')
def clear_web_servers():
    scripts = dict()
    for web_server in fab.env['httperf_lb']['servers']['web_server']:
        vm_id = web_server['vm_id']
        scripts[vm_id] = "sudo sed -i 's/Listen 8080/Listen 80/g' /etc/apache2/ports.conf; " \
                         "sudo sed -i 's/VirtualHost \*:8080/VirtualHost \*:80/g' " \
                         "/etc/apache2/sites-enabled/000-default.conf; " \
                         "sudo service apache2 stop; "
        scripts[vm_id] += "skill python; " \
                         "sudo sed -i 's/web_server_%s/_HOSTNAME_/g' ~/haproxy-dynamic-weight/request-lb-weight.py; " \
                          % (vm_id,)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_state_servers():
    scripts = dict()
    for state_server in fab.env['httperf_lb']['servers']['state_server']:
        vm_id = state_server['vm_id']
        scripts[vm_id] = "sudo docker stop state_server_%s; " \
                         "sudo docker rm state_server_%s; " \
                         "sudo service docker stop; " % (vm_id, vm_id)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_lb_servers():
    scripts = dict()
    for lb_server in fab.env['httperf_lb']['servers']['lb_server']:
        vm_id = lb_server['vm_id']
        policy = lb_server['policy']
        scripts[vm_id] = "skill python; " \
                         "sudo sed -i 's/\/var\/run\/haproxy.sock/\/etc\/haproxy\/haproxy.sock/g' " \
                         "~/haproxy-dynamic-weight/set-lb-weight.py; " \
                         "sudo rm -f /var/run/haproxy.sock; "
        scripts[vm_id] += \
            "sudo sed --in-place '/stats socket \/var\/run\/haproxy.sock mode 666 level admin/d' " \
            "/etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/frontend web-serving/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/bind %s%s:8080/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/default_backend web-serving-backend/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;" \
            "sudo sed --in-place '/balance %s/d' /etc/haproxy/haproxy.cfg; " \
            % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id, policy)
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = fab.env['httperf_lb']['servers']['web_server'][web_server_id]['vm_id']
            scripts[vm_id] += \
                "sudo sed --in-place '/server web_server_%s %s%s:8080/d' /etc/haproxy/haproxy.cfg; " \
                % (web_server_vm_id, fab.env['httperf_lb']['vm']['prefix_1'], web_server_vm_id)
        scripts[vm_id] += "sudo service haproxy stop; "
        scripts[vm_id] += "sudo ip addr del %s%s/24 dev eth1; " \
                          "sudo ip link set eth1 down; " \
                          % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_httperf_clients():
    scripts = dict()
    for httperf_client in fab.env['httperf_lb']['servers']['httperf_client']:
        vm_id = httperf_client['vm_id']
        scripts[vm_id] = "rm -f ~/httperf_script.sh; "
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['httperf_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear():
    proc_web = Process(target=clear_web_servers)
    proc_web.start()
    proc_state = Process(target=clear_state_servers)
    proc_state.start()
    proc_lb = Process(target=clear_lb_servers)
    proc_lb.start()
    proc_httperf = Process(target=clear_httperf_clients)
    proc_httperf.start()

    proc_web.join()
    proc_state.join()
    proc_lb.join()
    proc_httperf.join()


# The main functions are:
# 1. setup/cleanup
# 2. configure/clear
# 3. start
