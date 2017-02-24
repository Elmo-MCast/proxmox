import json
import os
from datetime import datetime
from multiprocessing import Process
import fabric.api as fab
import time

from pve import pve
from helpers import results

""" Configurations """

with open(os.path.dirname(__file__) + "/httperf_ipvs_lb.json") as json_file:
    settings = json.load(json_file)

fab.env.warn_only = settings['env']['warn_only']
fab.env.hosts = settings['env']['hosts']
fab.env.roledefs = settings['env']['roledefs']
fab.env.user = settings['env']['user']
fab.env.password = settings['env']['password']
fab.env['vm'] = settings['env']['vm']
fab.env['analyst'] = settings['env']['analyst']

fab.env['httperf_ipvs_lb'] = settings['httperf_ipvs_lb']

""" Helper Functions """

vm_id_set = set()
for server_name, server_configs in fab.env['httperf_ipvs_lb']['servers'].iteritems():
    for vm_config in server_configs["vms"]:
        vm_id = vm_config['vm_id']
        vm_id_set |= {vm_id}
vm_id_list = list(vm_id_set)

""" 'httperf_ipvs_lb' Commands """


@fab.roles('server')
def setup_scripts():
    scripts = list()
    script = \
        "sudo apt-get update; " \
        "sudo apt-get -y install libtool autoconf build-essential git cpulimit " \
        "ipvsadm apache2 bridge-utils python-memcache python-matplotlib python-psutil; " \
        "curl -sSL https://get.docker.com/ | sh; " \
        "git clone https://github.com/mshahbaz/httperf.git; " \
        "git clone https://github.com/mshahbaz/httperf-plot.git; " \
        "git clone https://github.com/mshahbaz/ipvs-dynamic-weight.git; " \
        "git clone https://github.com/mshahbaz/ipvs-utils.git; " \
        "cd ~/httperf; autoreconf -i; ./configure; make; sudo make install; cd ~/; " \
        "echo 'mshahbaz    hard    nofile      65535' | sudo tee -a /etc/security/limits.conf; " \
        "echo 'mshahbaz    soft    nofile      65535' | sudo tee -a /etc/security/limits.conf; " \
        "echo 'root        hard    nofile      65535' | sudo tee -a /etc/security/limits.conf; " \
        "echo 'root        soft    nofile      65535' | sudo tee -a /etc/security/limits.conf; " \
        "echo 'fs.file-max = 131071' | sudo tee -a /etc/sysctl.conf; " \
        "sudo sysctl -p; "
    scripts.append("echo '%s' > ~/setup_script.sh; " % (script,))
    scripts.append("sh ~/setup_script.sh; ")
    return scripts


@fab.roles('server')
def setup_options(vm_ids):
    # Note: setting options for state server first, so that it won't overwrite other servers' setting with whom
    # it may be sharing the VM.
    state_server = fab.env['httperf_ipvs_lb']['servers']['state_server']
    for state_server_vm in state_server['vms']:
        vm_id = state_server_vm['vm_id']
        sockets = state_server['options']['sockets']
        cores = state_server['options']['cores']
        memory = state_server['options']['memory']
        pve.vm_options(vm_id, "sockets", sockets)
        pve.vm_options(vm_id, "cores", cores)
        pve.vm_options(vm_id, "memory", memory)

    web_server = fab.env['httperf_ipvs_lb']['servers']['web_server']
    for web_server_vm in web_server['vms']:
        vm_id = web_server_vm['vm_id']
        sockets = web_server['options']['sockets']
        cores = web_server['options']['cores']
        memory = web_server['options']['memory']
        pve.vm_options(vm_id, "sockets", sockets)
        pve.vm_options(vm_id, "cores", cores)
        pve.vm_options(vm_id, "memory", memory)

    lb_server = fab.env['httperf_ipvs_lb']['servers']['lb_server']
    for lb_server_vm in lb_server['vms']:
        vm_id = lb_server_vm['vm_id']
        sockets = lb_server['options']['sockets']
        cores = lb_server['options']['cores']
        memory = lb_server['options']['memory']
        pve.vm_options(vm_id, "sockets", sockets)
        pve.vm_options(vm_id, "cores", cores)
        pve.vm_options(vm_id, "memory", memory)

    httperf_client = fab.env['httperf_ipvs_lb']['servers']['httperf_client']
    for httperf_client_vm in httperf_client['vms']:
        vm_id = httperf_client_vm['vm_id']
        sockets = httperf_client['options']['sockets']
        cores = httperf_client['options']['cores']
        memory = httperf_client['options']['memory']
        pve.vm_options(vm_id, "sockets", sockets)
        pve.vm_options(vm_id, "cores", cores)
        pve.vm_options(vm_id, "memory", memory)

    for vm_id in vm_ids:
        pve.vm_stop(vm_id)
        pve.vm_start(vm_id)
    for vm_id in vm_ids:
        pve.vm_is_ready(vm_id)


@fab.roles('server')
def setup():
    pve.vm_generate_multi(fab.env['httperf_ipvs_lb']['vm']['base_id'], "httperf-lb", False, setup_scripts(),
                          *vm_id_list)
    setup_options(vm_id_list)

    scripts = dict()
    for vm_id in vm_id_list:
        scripts[vm_id] = "sudo service docker stop; " \
                         "sudo service apache2 stop; " \
                         "sudo mv /var/www/html/index.html /var/www/html/index.html.orig; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def cleanup():
    pve.vm_destroy_multi(*vm_id_list)


@fab.roles('server')
def reboot():
    pve.vm_parallel_reboot(vm_id_list)
    for vm_id in vm_id_list:
        pve.vm_is_ready(vm_id)


@fab.roles('server')
def configure_web_servers():
    scripts = dict()
    web_server = fab.env['httperf_ipvs_lb']['servers']['web_server']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for web_server_vm in web_server['vms']:
        vm_id = web_server_vm['vm_id']
        lb_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms'][
            web_server_vm['lb_server']]['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         "sudo iptables -t nat -A PREROUTING -d %s%s.%s -j REDIRECT; " \
                         % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id,
                            vip_prefix, lb_server_vm_id, lb_server_vm_id)
        scripts[vm_id] += "sudo sed -i 's/Listen 80/Listen 8080/g' /etc/apache2/ports.conf; " \
                          "sudo sed -i 's/VirtualHost \*:80/VirtualHost \*:8080/g' " \
                          "/etc/apache2/sites-enabled/000-default.conf; "
        if web_server_vm['webpage']['cgi']['enable']:
            loop_count = web_server_vm['webpage']['cgi']['loop_count']
            scripts[vm_id] += \
                "sudo git clone https://gist.github.com/3b149ddc8521a265f89bdce11af84cfa.git; " \
                "sudo mv 3b149ddc8521a265f89bdce11af84cfa/cpu.py /usr/lib/cgi-bin/; " \
                "sudo rm -rf 3b149ddc8521a265f89bdce11af84cfa; " \
                "sudo sed -i 's/XXX/%s/g' /usr/lib/cgi-bin/cpu.py; " \
                "sudo sed -i 's/YYY/%s/g' /usr/lib/cgi-bin/cpu.py; " \
                "sudo chmod a+x /usr/lib/cgi-bin/cpu.py; " \
                "sudo sed -i 's/index.html index.cgi index.pl index.php index.xhtml index.htm/cgi-bin\/cpu.py/g' " \
                "/etc/apache2/mods-enabled/dir.conf;" \
                "sudo a2enmod cgid; " \
                % (vm_id, loop_count)
        else:
            scripts[vm_id] += "sudo echo '<!doctype html><html><body><h1>(Backend:%s)</h1></body></html>' " \
                              "| sudo tee -a /var/www/html/index.html; " \
                              % (vm_id)
        scripts[vm_id] += "sudo sync; " \
                          "sudo service apache2 start; "
        if fab.env['httperf_ipvs_lb']['feedback']['enable']:
            scripts[vm_id] += "sudo sed -i 's/server_id = _SERVER_ID_/server_id = %s/g' " \
                              "~/ipvs-dynamic-weight/request-lb-weight.py; " \
                              % (vm_id,)
            state_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['state_server']['vms'][
                web_server_vm['state_server']['id']]['vm_id']
            state_server_timeout = web_server_vm['state_server']['timeout']
            state_server_metric = web_server_vm['state_server']['metric']
            if state_server_metric == 'cpu':
                scripts[vm_id] += "nohup python ~/ipvs-dynamic-weight/request-lb-weight.py %s%s:11211 %s %s %s" \
                                  "> /dev/null 2> /dev/null < /dev/null & " \
                                  % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], state_server_vm_id,
                                     state_server_timeout, "False", state_server_metric)
            elif state_server_metric == 'loadavg':
                state_server_max_load = web_server_vm['state_server']['metrics'][state_server_metric]['max_load']
                scripts[vm_id] += "nohup python ~/ipvs-dynamic-weight/request-lb-weight.py %s%s:11211 %s %s %s %s" \
                                  "> /dev/null 2> /dev/null < /dev/null & " \
                                  % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], state_server_vm_id,
                                     state_server_timeout, "False", state_server_metric, state_server_max_load)
        if web_server_vm['load']['enable']:
            scripts[vm_id] += \
                "sudo git clone https://gist.github.com/453a427eaf2115fd7e0cf56f74a3d25c.git; " \
                "sudo mv 453a427eaf2115fd7e0cf56f74a3d25c/inf-loop.sh ./; " \
                "sudo rm -rf 453a427eaf2115fd7e0cf56f74a3d25c; "
            process_count = web_server_vm['load']['process_count']
            time_variance = web_server_vm['load']['time_variance']
            if web_server_vm['load']['type'] == 'cpulimit':
                percentage = web_server_vm['load']['types']['cpulimit']['percentage']
                scripts[vm_id] += \
                    "sudo git clone https://gist.github.com/e821e3239c274c102bf23080ef69090d.git; " \
                    "sudo mv e821e3239c274c102bf23080ef69090d/inf-loop-cpulimit.sh ./; " \
                    "sudo rm -rf e821e3239c274c102bf23080ef69090d; "
                if time_variance == 0:
                    scripts[vm_id] += \
                        "sudo nohup sh inf-loop-cpulimit.sh %s %s > /dev/null 2> /dev/null < /dev/null; " \
                        % (process_count, percentage)
                else:
                    scripts[vm_id] += \
                        "sudo git clone https://gist.github.com/b6a94c0303107806e21a4878241f995b.git; " \
                        "sudo mv b6a94c0303107806e21a4878241f995b/inf-loop-cpulimit-rand.sh ./; " \
                        "sudo rm -rf b6a94c0303107806e21a4878241f995b; " \
                        "sudo nohup sh inf-loop-cpulimit-rand.sh %s %s %s > /dev/null 2> /dev/null < /dev/null & " \
                        % (process_count, percentage, time_variance)
            elif web_server_vm['load']['type'] == 'nice':
                value = web_server_vm['load']['types']['nice']['value']
                scripts[vm_id] += \
                    "sudo git clone https://gist.github.com/72aa25cb9babfccba85f4b0004c3ad26.git; " \
                    "sudo mv 72aa25cb9babfccba85f4b0004c3ad26/inf-loop-nice.sh ./; " \
                    "sudo rm -rf 72aa25cb9babfccba85f4b0004c3ad26; "
                if time_variance == 0:
                    scripts[vm_id] += \
                        "sudo nohup sh inf-loop-nice.sh %s %s > /dev/null 2> /dev/null < /dev/null; " \
                        % (process_count, value)
                else:
                    scripts[vm_id] += \
                        "sudo git clone https://gist.github.com/35d3a537095b8b9a8eb873a1bb72abbb.git; " \
                        "sudo mv 35d3a537095b8b9a8eb873a1bb72abbb/inf-loop-nice-rand.sh ./; " \
                        "sudo rm -rf 35d3a537095b8b9a8eb873a1bb72abbb; " \
                        "sudo nohup sh inf-loop-nice-rand.sh %s %s %s > /dev/null 2> /dev/null < /dev/null & " \
                        % (process_count, value, time_variance)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_state_servers():
    if fab.env['httperf_ipvs_lb']['feedback']['enable']:
        scripts = dict()
        state_server = fab.env['httperf_ipvs_lb']['servers']['state_server']
        for state_server_vm in state_server['vms']:
            vm_id = state_server_vm['vm_id']
            scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                             "sudo ip link set eth1 up; " \
                             % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
            scripts[vm_id] += \
                "sudo service docker start; " \
                "sudo docker run --network=host --name state_server_%s -d memcached; " \
                % (vm_id,)
        pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_lb_servers():
    scripts = dict()
    lb_server = fab.env['httperf_ipvs_lb']['servers']['lb_server']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for lb_server_vm in lb_server['vms']:
        vm_id = lb_server_vm['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
        scripts[vm_id] += \
            "sudo sed -i 's/false/true/g' /etc/default/ipvsadm; " \
            "sudo sed -i 's/none/master/g' /etc/default/ipvsadm; " \
            "sudo sed -i 's/eth0/eth1/g' /etc/default/ipvsadm; "
        scripts[vm_id] += "sudo service ipvsadm start; " \
                          "sudo ifconfig eth1:0 %s%s.%s netmask 255.255.255.0 broadcast %s%s.255; " \
                          % (vip_prefix, vm_id, vm_id, vip_prefix, vm_id)
        policy = lb_server_vm['lb']['policy']
        scripts[vm_id] += "sudo ipvsadm -A -t %s%s.%s:8080 -s %s; " \
                          % (vip_prefix, vm_id, vm_id, policy)
        web_server_vm_ids = []
        for web_server_id in lb_server_vm['web_servers']:
            web_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['web_server']['vms'][
                web_server_id]['vm_id']
            scripts[vm_id] += \
                "sudo ipvsadm -a -t %s%s.%s:8080 -r %s%s:8080 -g; " \
                % (vip_prefix, vm_id, vm_id, fab.env['httperf_ipvs_lb']['vm']['prefix_1'], web_server_vm_id)
            web_server_vm_ids.append(str(web_server_vm_id))
        fin_timeout = lb_server_vm['lb']['fin_timeout']
        scripts[vm_id] += "sudo ipvsadm --set 0 %s 0; " % (fin_timeout,)
        if fab.env['httperf_ipvs_lb']['feedback']['enable']:
            state_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['state_server']['vms'][
                lb_server_vm['state_server']['id']]['vm_id']
            state_server_timeout = lb_server_vm['state_server']['timeout']
            scripts[vm_id] += "sudo sed -i 's/server_ids = \[_SERVER_IDS_\]/server_ids = \[%s\]/g' " \
                              "~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              "sudo sed -i 's/XXX/%s%s.%s/g' ~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              "sudo sed -i 's/YYY/%s/g' ~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              "nohup python ~/ipvs-dynamic-weight/set-lb-weight.py %s%s:11211 %s " \
                              "> /dev/null 2> /dev/null < /dev/null & " \
                              % (", ".join(web_server_vm_ids),
                                 vip_prefix, vm_id, vm_id,
                                 fab.env['httperf_ipvs_lb']['vm']['prefix_1'],
                                 fab.env['httperf_ipvs_lb']['vm']['prefix_1'], state_server_vm_id, state_server_timeout)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_httperf_clients():
    scripts = dict()
    httperf_client = fab.env['httperf_ipvs_lb']['servers']['httperf_client']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for httperf_client_vm in httperf_client['vms']:
        vm_id = httperf_client_vm['vm_id']
        lb_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms'][
            httperf_client_vm['lb_server']]['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         "sudo ip route add %s%s.0/24 dev eth1; " \
                         % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id,
                            vip_prefix, lb_server_vm_id)
        num_conns = httperf_client['config']['num_conns']
        num_calls = httperf_client['config']['num_calls']
        rate = httperf_client['config']['rate']
        ramp = httperf_client['config']['ramp']
        iters = httperf_client['config']['iters']
        timeout = httperf_client['config']['timeout']
        script = "cd ~/httperf-plot; " \
                 "python httperf-plot.py --server %s%s.%s --port 8080 " \
                 "--hog --verbose --num-conns %s --num-calls %s --rate %s " \
                 "--ramp-up %s,%s --timeout %s " \
                 "--csv %s > %s; " \
                 "cd ~/; " \
                 % (vip_prefix, lb_server_vm_id, lb_server_vm_id,
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
    for httperf_client in fab.env['httperf_ipvs_lb']['servers']['httperf_client']['vms']:
        vm_id = httperf_client['vm_id']
        if int(pve.vm_run(vm_id, 'netstat -t | wc -l')) > 100:
            fab.abort("too many TCP connections opened at client:%s" % (vm_id,))


@fab.roles('server')
def httperf_client_run():
    if fab.env['httperf_ipvs_lb']['stats']['enable']:
        pve.vm_parallel_run({lb_server['vm_id']:
                                 "sudo nohup python ~/ipvs-utils/dump-ipvsadm-L-n.py %s lb_server_%s.csv "
                                 "> /dev/null 2> /dev/null < /dev/null & "
                                 "sudo nohup python ~/ipvs-utils/dump-ipvsadm-L-n--stats.py %s lb_server_stats_%s.csv "
                                 "> /dev/null 2> /dev/null < /dev/null & "
                                 % (lb_server['stats']['timeout'], lb_server['vm_id'],
                                    lb_server['stats']['timeout'], lb_server['vm_id'])
                             for lb_server in fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms']})
    pve.vm_parallel_run({httperf_client['vm_id']: "sh ~/httperf_script.sh; "
                         for httperf_client in fab.env['httperf_ipvs_lb']['servers']['httperf_client']['vms']})
    if fab.env['httperf_ipvs_lb']['stats']['enable']:
        pve.vm_parallel_run({lb_server['vm_id']: "sudo pkill -u root python; "
                             for lb_server in fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms']})


@fab.roles('server')
def httperf_client_stop():
    pve.vm_parallel_run({httperf_client['vm_id']: "sudo skill httperf; "
                         for httperf_client in fab.env['httperf_ipvs_lb']['servers']['httperf_client']['vms']})


@fab.roles('server')
def post_httperf_client_run():
    datetime_str = str(datetime.now()).replace(':', '.').replace(' ', '.')
    fab.run("sshpass -p %s ssh %s 'mkdir %s/%s'; "
            % (fab.env.password, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
    for httperf_client in fab.env['httperf_ipvs_lb']['servers']['httperf_client']['vms']:
        vm_id = httperf_client['vm_id']
        pve.vm_get(vm_id, "~/httperf-plot/httperf_client_%s.*" % (vm_id,), "/tmp/; ")
        fab.run("sshpass -p %s scp /tmp/httperf_client_%s.* %s:%s/%s/; "
                % (fab.env.password, vm_id, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
        pve.vm_run(vm_id, "rm -f ~/httperf-plot/httperf_client_%s.*; " % (vm_id,))
        fab.run("rm -f /tmp/httperf_client_%s.*; " % (vm_id,))
    if fab.env['httperf_ipvs_lb']['stats']['enable']:
        for lb_server in fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms']:
            vm_id = lb_server['vm_id']
            pve.vm_get(vm_id, "~/lb_server_*%s.*" % (vm_id,), "/tmp/; ")
            fab.run("sshpass -p %s scp /tmp/lb_server_*%s.* %s:%s/%s/; "
                    % (
                        fab.env.password, vm_id, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'],
                        datetime_str))
            pve.vm_run(vm_id, "rm -f ~/lb_server_*%s.*; " % (vm_id,))
            fab.run("rm -f /tmp/lb_server_*%s.*; " % (vm_id,))


@fab.roles('server')
def start():
    httperf_client_is_ready()
    httperf_client_run()
    post_httperf_client_run()


@fab.roles('server')
def stop():
    httperf_client_stop()


@fab.roles('server')
def clear_web_servers():
    scripts = dict()
    web_server = fab.env['httperf_ipvs_lb']['servers']['web_server']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for web_server_vm in web_server['vms']:
        vm_id = web_server_vm['vm_id']
        scripts[vm_id] = ""
        if web_server_vm['load']['enable']:
            scripts[vm_id] += "sudo skill sh; " \
                              "sudo rm -f inf-loop.sh; "
            time_variance = web_server_vm['load']['time_variance']
            if web_server_vm['load']['type'] == 'cpulimit':
                scripts[vm_id] += "sudo rm -f inf-loop-cpulimit.sh; "
                if time_variance != 0:
                    scripts[vm_id] += "sudo rm -f inf-loop-cpulimit-rand.sh; "
            elif web_server_vm['load']['type'] == 'nice':
                scripts[vm_id] += "sudo rm -f inf-loop-nice.sh; "
                if time_variance != 0:
                    scripts[vm_id] += "sudo rm -f inf-loop-nice-rand.sh; "
        if fab.env['httperf_ipvs_lb']['feedback']['enable']:
            scripts[vm_id] += "skill python; " \
                              "sudo sed -i 's/server_id = %s/server_id = _SERVER_ID_/g' " \
                              "~/ipvs-dynamic-weight/request-lb-weight.py; " \
                              % (vm_id,)
        scripts[vm_id] += "sudo sed -i 's/Listen 8080/Listen 80/g' /etc/apache2/ports.conf; " \
                          "sudo sed -i 's/VirtualHost \*:8080/VirtualHost \*:80/g' " \
                          "/etc/apache2/sites-enabled/000-default.conf; "
        if web_server_vm['webpage']['cgi']['enable']:
            scripts[vm_id] += \
                "sudo rm -f /usr/lib/cgi-bin/cpu.py; " \
                "sudo sed -i 's/cgi-bin\/cpu.py/index.html index.cgi index.pl index.php index.xhtml index.htm/g' " \
                "/etc/apache2/mods-enabled/dir.conf;" \
                "sudo a2dismod cgid; "
        else:
            scripts[vm_id] += "sudo rm -f /var/www/html/index.html; "
        scripts[vm_id] += "sudo sync; " \
                          "sudo service apache2 stop; "
        lb_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms'][
            web_server_vm['lb_server']]['vm_id']
        scripts[vm_id] += \
            "sudo iptables -t nat -D PREROUTING -d %s%s.%s -j REDIRECT; " \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (vip_prefix, lb_server_vm_id, lb_server_vm_id,
               fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_state_servers():
    if fab.env['httperf_ipvs_lb']['feedback']['enable']:
        scripts = dict()
        state_server = fab.env['httperf_ipvs_lb']['servers']['state_server']
        for state_server_vm in state_server['vms']:
            vm_id = state_server_vm['vm_id']
            scripts[vm_id] = "sudo docker stop state_server_%s; " \
                             "sudo docker rm state_server_%s; " \
                             "sudo service docker stop; " % (vm_id, vm_id)
            scripts[vm_id] += \
                "sudo ip addr del %s%s/24 dev eth1; " \
                "sudo ip link set eth1 down; " \
                % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
        pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_lb_servers():
    scripts = dict()
    lb_server = fab.env['httperf_ipvs_lb']['servers']['lb_server']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for lb_server_vm in lb_server['vms']:
        web_server_vm_ids = []
        for web_server_id in lb_server_vm['web_servers']:
            web_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['web_server']['vms'][
                web_server_id]['vm_id']
            web_server_vm_ids.append(str(web_server_vm_id))
        vm_id = lb_server_vm['vm_id']
        scripts[vm_id] = "sudo ipvsadm --set 0 120 0; "
        if fab.env['httperf_ipvs_lb']['feedback']['enable']:
            scripts[vm_id] += "skill python; " \
                              "sudo sed -i 's/server_ids = \[%s\]/server_ids = \[_SERVER_IDS_\]/g' " \
                              "~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              "sudo sed -i 's/%s%s.%s/XXX/g' ~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              "sudo sed -i 's/%s/YYY/g' ~/ipvs-dynamic-weight/set-lb-weight.py; " \
                              % (", ".join(web_server_vm_ids),
                                 vip_prefix, vm_id, vm_id,
                                 fab.env['httperf_ipvs_lb']['vm']['prefix_1'])
        scripts[vm_id] += "sudo ipvsadm -C; " \
                          "sudo ifconfig eth1:0 down; " \
                          "sudo service ipvsadm stop; "
        scripts[vm_id] += \
            "sudo sed -i 's/true/false/g' /etc/default/ipvsadm; " \
            "sudo sed -i 's/master/none/g' /etc/default/ipvsadm; " \
            "sudo sed -i 's/eth1/eth0/g' /etc/default/ipvsadm; "
        scripts[vm_id] += "sudo ip addr del %s%s/24 dev eth1; " \
                          "sudo ip link set eth1 down; " \
                          % (fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def clear_httperf_clients():
    scripts = dict()
    httperf_client = fab.env['httperf_ipvs_lb']['servers']['httperf_client']
    vip_prefix = fab.env['httperf_ipvs_lb']['vip']['prefix']
    for httperf_client_vm in httperf_client['vms']:
        vm_id = httperf_client_vm['vm_id']
        lb_server_vm_id = fab.env['httperf_ipvs_lb']['servers']['lb_server']['vms'][
            httperf_client_vm['lb_server']]['vm_id']
        scripts[vm_id] = "rm -f ~/httperf_script.sh; "
        scripts[vm_id] += \
            "sudo ip route del %s%s.0/24 dev eth1; " \
            "sudo ip addr del %s%s/24 dev eth1; " \
            "sudo ip link set eth1 down; " \
            % (vip_prefix, lb_server_vm_id,
               fab.env['httperf_ipvs_lb']['vm']['prefix_1'], vm_id)
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
