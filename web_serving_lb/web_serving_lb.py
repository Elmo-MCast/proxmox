import json
import os
from multiprocessing import Process

import fabric.api as fab

from pve import pve
from helpers import results

""" Configurations """

with open(os.path.dirname(__file__) + "/web_serving_lb.json") as json_file:
    settings = json.load(json_file)

fab.env.warn_only = settings['env']['warn_only']
fab.env.hosts = settings['env']['hosts']
fab.env.roledefs = settings['env']['roledefs']
fab.env.user = settings['env']['user']
fab.env.password = settings['env']['password']
fab.env['vm'] = settings['env']['vm']

fab.env['web_serving_lb'] = settings['web_serving_lb']

""" Helper Functions """

vm_id_set = set()
server_vm_id_map = {}
for server_name, server_configs in fab.env['web_serving_lb']['servers'].iteritems():
    for server_config in server_configs:
        vm_id = server_config['vm_id']
        vm_id_set |= {vm_id}
        server_vm_id_map[server_name + '_%s' % (vm_id,)] = '%s' % (vm_id,)
vm_id_list = list(vm_id_set)

""" 'web_serving_lb' Commands """


@fab.roles('server')
def setup_scripts():
    scripts = list()
    script = \
        "sudo apt-get update; " \
        "curl -sSL https://get.docker.com/ | sh; " \
        "sudo apt-get -y install haproxy bridge-utils python-memcache; " \
        "git clone https://github.com/mshahbaz/haproxy-dynamic-weight.git; "
    # # Add hosts
    # for server_name, server_vm_id in server_vm_id_map.iteritems():
    #     script += "echo %s%s %s | sudo tee -a /etc/hosts; " \
    #               % (fab.env['web_serving_lb']['vm']['prefix_1'], server_vm_id, server_name)
    scripts.append("echo '%s' > ~/setup_script.sh; " % (script,))
    scripts.append("sh ~/setup_script.sh; ")
    return scripts


@fab.roles('server')
def setup():
    pve.vm_generate_multi(fab.env['web_serving_lb']['vm']['base_id'], "web-serving-lb", False, setup_scripts(),
                          *vm_id_list)


@fab.roles('server')
def cleanup():
    pve.vm_destroy_multi(*vm_id_list)


@fab.roles('server')
def configure_mysql_servers():
    scripts = dict()
    for mysql_server in fab.env['web_serving_lb']['servers']['mysql_server']:
        vm_id = mysql_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        lb_server_vm_id = fab.env['web_serving_lb']['servers']['lb_server'][mysql_server['lb_server']]['vm_id']
        scripts[vm_id] += \
            "sudo docker run -dt --net host --name mysql_server_%s cloudsuite/web-serving:db_server %s%s; " \
            % (vm_id, fab.env['web_serving_lb']['vm']['prefix_1'], lb_server_vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_memcache_servers():
    scripts = dict()
    for memcache_server in fab.env['web_serving_lb']['servers']['memcache_server']:
        vm_id = memcache_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += \
            "sudo docker run -dt --net=host --name=memcache_server_%s cloudsuite/web-serving:memcached_server; " \
            % (vm_id,)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_web_servers():
    scripts = dict()
    for web_server in fab.env['web_serving_lb']['servers']['web_server']:
        vm_id = web_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        pm_max_childs = web_server['pm_max_childs']
        mysql_server_vm_id = fab.env['web_serving_lb']['servers']['mysql_server'][web_server['mysql_server']]['vm_id']
        memcache_server_vm_id = \
            fab.env['web_serving_lb']['servers']['memcache_server'][web_server['memcache_server']]['vm_id']
        scripts[vm_id] += \
            "sudo docker run -dt --net=host --name=web_server_%s cloudsuite/web-serving:web_server " \
            "/etc/bootstrap.sh %s%s %s%s %s; " \
            % (vm_id,
               fab.env['web_serving_lb']['vm']['prefix_1'], mysql_server_vm_id,
               fab.env['web_serving_lb']['vm']['prefix_1'], memcache_server_vm_id,
               pm_max_childs)
        scripts[vm_id] += "sudo sed -i 's/_HOSTNAME_/web_server_%s/g' ~/haproxy-dynamic-weight/request-lb-weight.py; " \
                          % (vm_id,)
        state_server_vm_id = fab.env['web_serving_lb']['servers']['state_server'][
            web_server['state_server']['id']]['vm_id']
        state_server_timeout = web_server['state_server']['timeout']
        state_server_max_load = web_server['state_server']['max_load']
        scripts[vm_id] += "nohup python ~/haproxy-dynamic-weight/request-lb-weight.py %s%s:11211 %s %s " \
                          "> /dev/null 2> /dev/null < /dev/null & " \
                          % (fab.env['web_serving_lb']['vm']['prefix_1'], state_server_vm_id,
                             state_server_timeout, state_server_max_load)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_faban_clients():
    scripts = dict()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_client']:
        vm_id = faban_client['vm_id']
        scripts[vm_id] = "sudo docker network create --driver bridge --subnet=%s0/24 --gateway=%s%s " \
                         "--opt 'com.docker.network.bridge.name'='docker1' docker1; " \
                         "sudo brctl addif docker1 eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'],
                            fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        steady_state = faban_client['steady_state']
        for client_id in faban_client['clients']:
            scripts[vm_id] += \
                "sudo docker run -dt --net docker1 --ip %s%s --name faban_client_%s --entrypoint bash " \
                "cloudsuite/web-serving:faban_client; " \
                % (fab.env['web_serving_lb']['vm']['prefix_1'], client_id, client_id)
            scripts[vm_id] += \
                "sudo docker exec faban_client_%s sudo sed -i 's/<fa:steadyState>30/<fa:steadyState>%s/g' " \
                "/etc/bootstrap.sh; " % (client_id, steady_state)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_state_servers():
    scripts = dict()
    for state_server in fab.env['web_serving_lb']['servers']['state_server']:
        vm_id = state_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += \
            "sudo docker run --network=host --name state_server_%s -d memcached; " \
            % (vm_id,)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_lb_servers():
    scripts = dict()
    for lb_server in fab.env['web_serving_lb']['servers']['lb_server']:
        vm_id = lb_server['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        policy = lb_server['policy']
        scripts[vm_id] += \
            "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy; " \
            "sudo sed -i '8istats socket /var/run/haproxy.sock mode 666 level admin' /etc/haproxy/haproxy.cfg; " \
            "echo 'frontend web-serving' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    bind %s%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    default_backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo 'backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo '    balance %s' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id, policy)
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = fab.env['web_serving_lb']['servers']['web_server'][web_server_id]['vm_id']
            scripts[vm_id] += \
                "echo '    server web_server_%s %s%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg; " \
                % (web_server_vm_id, fab.env['web_serving_lb']['vm']['prefix_1'], web_server_vm_id)
        scripts[vm_id] += "sudo service haproxy stop; " \
                          "sudo service haproxy start; "
        state_server_vm_id = fab.env['web_serving_lb']['servers']['state_server'][
            lb_server['state_server']['id']]['vm_id']
        state_server_timeout = lb_server['state_server']['timeout']
        scripts[vm_id] += "sudo sed -i 's/\/etc\/haproxy\/haproxy.sock/\/var\/run\/haproxy.sock/g' " \
                          "~/haproxy-dynamic-weight/set-lb-weight.py; " \
                          "nohup python ~/haproxy-dynamic-weight/set-lb-weight.py %s%s:11211 %s " \
                          "> /dev/null 2> /dev/null < /dev/null & " \
                          % (fab.env['web_serving_lb']['vm']['prefix_1'], state_server_vm_id, state_server_timeout)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure():
    proc_mysql = Process(target=configure_mysql_servers)
    proc_mysql.start()
    proc_memcache = Process(target=configure_memcache_servers)
    proc_memcache.start()
    proc_web = Process(target=configure_web_servers)
    proc_web.start()
    proc_faban = Process(target=configure_faban_clients)
    proc_faban.start()
    proc_lb = Process(target=configure_lb_servers)
    proc_lb.start()
    proc_state = Process(target=configure_state_servers)
    proc_state.start()

    proc_mysql.join()
    proc_memcache.join()
    proc_web.join()
    proc_faban.join()
    proc_lb.join()
    proc_state.join()


@fab.roles('server')
def pre_faban_client_run():
    scripts = list()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_client']:
        for client_id in faban_client['clients']:
            scripts.append("rm -f results/faban_client_%s.log" % (client_id,))
    pve.local_parallel_run(scripts)


@fab.roles('server')
def faban_client_run():
    scripts = dict()
    client_ids = list()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_client']:
        vm_id = faban_client['vm_id']
        load_scale = faban_client['load_scale']
        lb_server_vm_id = fab.env['web_serving_lb']['servers']['lb_server'][faban_client['lb_server']]['vm_id']
        scripts[vm_id] = list()
        for client_id in faban_client['clients']:
            scripts[vm_id].append(
                "sudo docker exec faban_client_%s /etc/bootstrap.sh %s%s %s > %s"
                % (client_id, fab.env['web_serving_lb']['vm']['prefix_1'], lb_server_vm_id, load_scale,
                   "faban_client_%s.log" % (client_id,)))
            client_ids.append(client_id)
    pve.vm_parallel_run(scripts)
    return client_ids


@fab.roles('server')
def post_faban_client_run():
    vm_get_scripts = dict()
    get_scripts = list()
    vm_run_scripts = dict()
    run_scripts = list()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_client']:
        vm_id = faban_client['vm_id']
        vm_get_scripts[vm_id] = list()
        vm_run_scripts[vm_id] = list()
        for client_id in faban_client['clients']:
            vm_get_scripts[vm_id].append({'src': "faban_client_%s.log" % (client_id,),
                                          'dst': "/tmp/"})
            get_scripts.append({'src': "/tmp/faban_client_%s.log" % (client_id,),
                                'dst': "results/"})
            vm_run_scripts[vm_id].append("rm -f faban_client_%s.log" % (client_id,))
            run_scripts.append("rm -f /tmp/faban_client_%s.log" % (client_id,))
    pve.vm_parallel_get(vm_get_scripts)
    pve.parallel_get(get_scripts)
    pve.vm_parallel_run(vm_run_scripts)
    pve.parallel_run(run_scripts)


@fab.roles('server')
def print_results(client_ids):
    for client_id in client_ids:
        print 'faban_client_%s' % (client_id,) + str(
            results.clean_results('results/faban_client_%s.log' % (client_id,)))


@fab.roles('server')
def start():
    pre_faban_client_run()
    client_ids = faban_client_run()
    post_faban_client_run()
    print_results(client_ids)


@fab.roles('server')
def clear_mysql_servers():
    scripts = dict()
    for mysql_server in fab.env['web_serving_lb']['servers']['mysql_server']:
        vm_id = mysql_server['vm_id']
        scripts[vm_id] = "sudo docker stop mysql_server_%s; " \
                         "sudo docker rm mysql_server_%s; " % (vm_id, vm_id)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_memcache_servers():
    scripts = dict()
    for memcache_server in fab.env['web_serving_lb']['servers']['memcache_server']:
        vm_id = memcache_server['vm_id']
        scripts[vm_id] = "sudo docker stop memcache_server_%s; " \
                         "sudo docker rm memcache_server_%s; " % (vm_id, vm_id)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_web_servers():
    scripts = dict()
    for web_server in fab.env['web_serving_lb']['servers']['web_server']:
        vm_id = web_server['vm_id']
        scripts[vm_id] = "skill python; " \
                         "sudo sed -i 's/web_server_%s/_HOSTNAME_/g' ~/haproxy-dynamic-weight/request-lb-weight.py; " \
                          % (vm_id,)
        scripts[vm_id] += "sudo docker stop web_server_%s;" \
                          "sudo docker rm web_server_%s; " % (vm_id, vm_id)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_faban_clients():
    scripts = dict()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_client']:
        vm_id = faban_client['vm_id']
        scripts[vm_id] = ""
        for client_id in faban_client['clients']:
            scripts[vm_id] += "sudo docker stop faban_client_%s; " \
                              "sudo docker rm faban_client_%s; " \
                              % (client_id, client_id)
        scripts[vm_id] += "sudo ip link set eth1 down; " \
                          "sudo brctl delif docker1 eth1; " \
                          "sudo docker network rm docker1; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_state_servers():
    scripts = dict()
    for state_server in fab.env['web_serving_lb']['servers']['state_server']:
        vm_id = state_server['vm_id']
        scripts[vm_id] = "sudo docker stop state_server_%s; " \
                         "sudo docker rm state_server_%s; " % (vm_id, vm_id)
        scripts[vm_id] += \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_lb_servers():
    scripts = dict()
    for lb_server in fab.env['web_serving_lb']['servers']['lb_server']:
        vm_id = lb_server['vm_id']
        policy = lb_server['policy']
        scripts[vm_id] = "skill python; "
        scripts[vm_id] += \
            "sudo sed --in-place '/stats socket \/var\/run\/haproxy.sock mode 666 level admin/d' " \
            "/etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/frontend web-serving/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/bind %s%s:8080/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/default_backend web-serving-backend/d' /etc/haproxy/haproxy.cfg; " \
            "sudo sed --in-place '/backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;" \
            "sudo sed --in-place '/balance %s/d' /etc/haproxy/haproxy.cfg; " \
            % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id, policy)
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = fab.env['web_serving_lb']['servers']['web_server'][web_server_id]['vm_id']
            scripts[vm_id] += \
                "sudo sed --in-place '/server web_server_%s %s%s:8080/d' /etc/haproxy/haproxy.cfg; " \
                % (web_server_vm_id, fab.env['web_serving_lb']['vm']['prefix_1'], web_server_vm_id)
        scripts[vm_id] += "sudo service haproxy stop; "
        scripts[vm_id] += "sudo ip addr del %s%s/24 dev eth1; " \
                          "sudo ip link set eth1 down; " \
                          % (fab.env['web_serving_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += "sudo sed -i 's/\/var\/run\/haproxy.sock/\/etc\/haproxy\/haproxy.sock/g' " \
                          "~/haproxy-dynamic-weight/set-lb-weight.py; " \
                          "sudo rm -f /var/run/haproxy.sock; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear():
    proc_mysql = Process(target=clear_mysql_servers)
    proc_mysql.start()
    proc_memcache = Process(target=clear_memcache_servers)
    proc_memcache.start()
    proc_web = Process(target=clear_web_servers)
    proc_web.start()
    proc_faban = Process(target=clear_faban_clients)
    proc_faban.start()
    proc_lb = Process(target=clear_lb_servers)
    proc_lb.start()
    proc_state = Process(target=clear_state_servers)
    proc_state.start()

    proc_mysql.join()
    proc_memcache.join()
    proc_web.join()
    proc_faban.join()
    proc_lb.join()
    proc_state.join()

# The main functions are:
# 1. setup/cleanup
# 2. configure/clear
# 3. start
