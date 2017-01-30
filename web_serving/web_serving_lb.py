import os
import json
import fabric.api as fab
from pebble import process

from common import pve
from web_serving.helpers import results

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
def add_hosts():
    scripts = dict()
    for vm_id in vm_id_list:
        for server_name, server_vm_id in server_vm_id_map.iteritems():
            scripts[vm_id] = "echo '%s%s %s' | sudo tee -a /etc/hosts; " \
                             % (fab.env['vm']['prefix'], server_vm_id, server_name)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def generate():
    pve.vm_generate_multi(fab.env['web_serving_lb']['vm']['base_id'], "web_serving_lb", *vm_id_list)
    add_hosts()


@fab.roles('server')
def destroy():
    pve.vm_destroy_multi(*vm_id_list)


@fab.roles('server')
def configure_common():
    scripts = dict()
    for vm_id in vm_id_list:
        pve.vm_is_ready(vm_id)
        scripts[vm_id] = "sudo apt-get update;"\
                         "curl -sSL https://get.docker.com/ | sh;"\
                         "sudo apt-get install haproxy;"\
                         "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_mysql_servers():
    scripts = dict()
    for mysql_server in fab.env['web_serving_lb']['servers']['mysql_servers']:
        vm_id = mysql_server['vm_id']
        lb_server_vm_id = fab.env['web_serving_lb']['servers']['lb_servers'][mysql_server['lb_server']]['vm_id']
        pve.vm_is_ready(vm_id)
        scripts[vm_id] = \
            "sudo docker start -dt --net host --name mysql_server_%s cloudsuite/web-serving:db_server %s%s; " \
            % (vm_id, fab.env['vm']['prefix'], lb_server_vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_memcache_servers():
    scripts = dict()
    for memcache_server in fab.env['web_serving_lb']['servers']['memcache_servers']:
        vm_id = memcache_server['vm_id']
        pve.vm_is_ready(vm_id)
        scripts[vm_id] = \
            "sudo docker start -dt --net=host --name=memcache_server_%s cloudsuite/web-serving:memcached_server; " \
            % (vm_id,)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_web_servers():
    scripts = dict()
    for web_server in fab.env['web_serving_lb']['servers']['web_servers']:
        vm_id = web_server['vm_id']
        pm_max_childs = web_server['pm_max_childs']
        mysql_server_vm_id = settings['vms']['mysql_server'][web_server['mysql_server']]['vm_id']
        memcache_server_vm_id = settings['vms']['memcache_server'][web_server['memcache_server']]['vm_id']
        pve.vm_is_ready(vm_id)
        scripts[vm_id] = \
            "sudo docker start -dt --net=host --name=web_server_%s cloudsuite/web-serving:web_server " \
            "/etc/bootstrap.sh mysql_server_%s memcache_server_%s %s; " \
            % (vm_id, mysql_server_vm_id, memcache_server_vm_id, pm_max_childs)
    pve.vm_parallel_run(scripts)


@fab.roles('server')
def configure_faban_clients():
    scripts = dict()
    for faban_client in fab.env['web_serving_lb']['servers']['faban_clients']:
        vm_id = faban_client['vm_id']
        steady_state = faban_client['steady_state']
        pve.vm_is_ready(vm_id)
        script = ""
        for client_id in faban_client['clients']:
            script += "sudo docker start -dt --net none --name faban_client_%s --entrypoint bash " \
                      "cloudsuite/web-serving:faban_client; " % (client_id,)
            script += "sudo ./pipework/pipework br0 -i eth0 faban_client_%s %s%s/24; " \
                      % (client_id, fab.env['vm']['prefix'], client_id)
            script += "sudo docker exec faban_client_%s sudo sed -i 's/<fa:steadyState>30/<fa:steadyState>%s/g' " \
                      "/etc/bootstrap.sh; " % (client_id, steady_state)
        scripts[vm_id] = script


@fab.roles('server')
def configure_lb_servers():
    scripts = dict()
    for lb_server in fab.env['web_serving_lb']['servers']['lb_servers']:
        vm_id = lb_server['vm_id']
        policy = lb_server['policy']
        pve.vm_is_ready(vm_id)
        scripts[vm_id] = "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy; "
        scripts[vm_id] += \
            "echo 'frontend web-serving\n    bind %s%s:8080\n    default_backend web-serving-backend' | " \
            "sudo tee -a /etc/haproxy/haproxy.cfg; " \
            "echo 'backend web-serving-backend\n    balance %s' | sudo tee -a /etc/haproxy/haproxy.cfg; "\
            % (fab.env['vm']['prefix'], vm_id, policy)
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = settings['vms']['web_server'][web_server_id]['vm_id']
            scripts[vm_id] +=\
                "echo '    server web_server_%s %s%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg; "\
                % (web_server_vm_id, fab.env['vm']['prefix'], web_server_vm_id)
        scripts[vm_id] += "sudo service haproxy stop; "
        scripts[vm_id] += "sudo service haproxy start; "
    pve.vm_parallel_run(scripts)


@fab.roles('server')
@process.spawn(daemon=True)
def configure():
    run_mysql = configure_mysql_servers()
    run_memcache = configure_memcache_servers()
    run_web = configure_web_servers()
    run_faban = configure_faban_clients()
    run_lb = configure_lb_servers()

    run_mysql.join()
    run_memcache.join()
    run_web.join()
    run_faban.join()
    run_lb.join()





# @fab.roles('server')
# @process.spawn(daemon=True)
# def run_faban_client(vm_id, client_id, web_server_vm_id, load_scale):
#     fab.local("rm -f results/faban_client_%s.log" % (client_id,))
#     pve.vm_run(vm_id,
#                 "sudo docker exec faban_client_%s /etc/bootstrap.sh 10.10.10.%s %s"
#                 % (client_id, web_server_vm_id, load_scale),
#                 "/tmp/faban_client_%s.log" % (client_id,))
#     fab.get("/tmp/faban_client_%s.log" % (client_id,), "results/")
#     fab.start("rm -f /tmp/faban_client_%s.log" % (client_id,))
#
#
# def start():
#     runs = []
#     for faban_client in settings['vms']['faban_client']:
#         vm_id = faban_client['vm_id']
#         load_scale = faban_client['load_scale']
#         lb_server_vm_id = settings['vms']['lb_server'][faban_client['lb_server']]['vm_id']
#         for client_id in faban_client['clients']:
#             runs.append({
#                 'start': run_faban_client(vm_id, client_id, lb_server_vm_id, load_scale),
#                 'client_id': client_id})
#     for i in range(len(runs)):
#         runs[i]['start'].join()
#         print 'faban_client_%s' % (runs[i]['client_id'],) + str(
#             results.clean_results('results/faban_client_%s.log' % (runs[i]['client_id'],)))
#
#
# def clear_mysql_server():
#     for mysql_server in settings['vms']['mysql_server']:
#         vm_id = mysql_server['vm_id']
#         pve.vm_is_ready(vm_id)
#         pve.vm_run(vm_id,
#                     "sudo docker stop mysql_server_%s;"
#                     "sudo docker rm mysql_server_%s" % (vm_id, vm_id))
#
#
# def clear_memcache_server():
#     for memcache_server in settings['vms']['memcache_server']:
#         vm_id = memcache_server['vm_id']
#         pve.vm_is_ready(vm_id)
#         pve.vm_run(vm_id,
#                     "sudo docker stop memcache_server_%s;"
#                     "sudo docker rm memcache_server_%s" % (vm_id, vm_id))
#
#
# def clear_web_server():
#     for web_server in settings['vms']['web_server']:
#         vm_id = web_server['vm_id']
#         pve.vm_is_ready(vm_id)
#         pve.vm_run(vm_id,
#                     "sudo docker stop web_server_%s;"
#                     "sudo docker rm web_server_%s" % (vm_id, vm_id))
#
#
# def clear_lb_server():
#     for lb_server in settings['vms']['lb_server']:
#         vm_id = lb_server['vm_id']
#         policy = lb_server['policy']
#         pve.vm_is_ready(vm_id)
#         pve.vm_run(vm_id,
#                     "sudo sed --in-place '/frontend web-serving/d' /etc/haproxy/haproxy.cfg;"
#                     "sudo sed --in-place '/bind 10.10.10.%s:8080/d' /etc/haproxy/haproxy.cfg;"
#                     "sudo sed --in-place '/default_backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;"
#                     "sudo sed --in-place '/backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;"
#                     "sudo sed --in-place '/balance %s/d' /etc/haproxy/haproxy.cfg"
#                     % (vm_id, policy))
#         for web_server_id in lb_server['web_servers']:
#             web_server_vm_id = settings['vms']['web_server'][web_server_id]['vm_id']
#             pve.vm_run(vm_id,
#                         "sudo sed --in-place '/server web_server_%s 10.10.10.%s:8080/d' /etc/haproxy/haproxy.cfg"
#                         % (web_server_vm_id, web_server_vm_id))
#         pve.vm_run(vm_id, "sudo service haproxy stop")
#
#
# def clear_faban_client(vm_id):
#     pve.vm_run(vm_id,
#                 "sudo docker stop faban_client_%s;"
#                 "sudo docker rm faban_client_%s" % (vm_id, vm_id))
#
#
# def clear():
#     clear_mysql_server()
#     clear_memcache_server()
#     clear_web_server()
#     clear_lb_server()
#     for faban_client in settings['vms']['faban_client']:
#         vm_id = faban_client['vm_id']
#         clear_faban_client(vm_id)
#
