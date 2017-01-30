import fabric.api as fab
from pebble import process

from common import pve
from web_serving import results

# Settings

settings = {
    'vms': {
        'mysql_server': [
            {'vm_id': 206, 'lb_server': 0},
            # {'vm_id': 207, 'lb_server': 0},
            # {'vm_id': 208, 'lb_server': 0},
            # {'vm_id': 209, 'lb_server': 0}
        ],
        'memcache_server': [
            {'vm_id': 206},
            # {'vm_id': 207},
            # {'vm_id': 208},
            # {'vm_id': 209}
        ],
        'web_server': [
            {'vm_id': 207, 'pm_max_childs': 80, 'mysql_server': 0, 'memcache_server': 0},
            {'vm_id': 208, 'pm_max_childs': 80, 'mysql_server': 0, 'memcache_server': 0},
            {'vm_id': 209, 'pm_max_childs': 80, 'mysql_server': 0, 'memcache_server': 0},
            {'vm_id': 210, 'pm_max_childs': 80, 'mysql_server': 0, 'memcache_server': 0}
        ],
        'faban_client': [
            {'vm_id': 211, 'load_scale': 1, 'steady_state': 30, 'lb_server': 0, 'clients': [212, 213, 214, 215, 216, 217]},
            {'vm_id': 218, 'load_scale': 1, 'steady_state': 30, 'lb_server': 0, 'clients': [219, 220, 221, 222, 223, 224]}
        ],
        'lb_server': [
            {'vm_id': 205, 'web_servers': [0, 1, 2, 3], 'policy': 'roundrobin'}
            # RoundRobin policy requires centralized authentication and state sharing ... this can be done using a single
            # mysql and memcache server, for now.
        ]
    },
    'vm_prefix': 'web-serving-lb',
    'base_vm_id': 196
}

# Helpers

vm_id_set = set()
server_vm_id_map = {}

for server_name, server_configs in settings['vms'].iteritems():
    for server_config in server_configs:
        vm_id = server_config['vm_id']
        vm_id_set |= {vm_id}
        server_vm_id_map[server_name + '_%s' % (vm_id,)] = '%s' % (vm_id,)

vm_id_list = list(vm_id_set)


# Commands

def add_hosts():
    for vm_id in vm_id_list:
        for server_name, server_vm_id in server_vm_id_map.iteritems():
            pve.vm_add_host(vm_id, server_vm_id, server_name)


def generate():
    pve.vm_generate_multi(settings['base_vm_id'], settings['vm_prefix'], *vm_id_list)
    add_hosts()


def destroy():
    pve.vm_destroy_multi(*vm_id_list)


# def configure_common():
#     for vm_id in vm_id_list:
#         pve.vm_is_ready(vm_id)
#         pve.vm_run(vm_id,
#                     "sudo apt-get update;"
#                     "curl -sSL https://get.docker.com/ | sh;"
#                     "sudo apt-get install haproxy;"
#                     "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy")


@process.spawn(daemon=True)
def configure_mysql_server():
    for mysql_server in settings['vms']['mysql_server']:
        vm_id = mysql_server['vm_id']
        lb_server_vm_id = settings['vms']['lb_server'][mysql_server['lb_server']]['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker start -dt --net host --name mysql_server_%s cloudsuite/web-serving:db_server 10.10.10.%s"
                   % (vm_id, lb_server_vm_id,))


@process.spawn(daemon=True)
def configure_memcache_server():
    for memcache_server in settings['vms']['memcache_server']:
        vm_id = memcache_server['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker start -dt --net=host --name=memcache_server_%s cloudsuite/web-serving:memcached_server"
                   % (vm_id,))


@process.spawn(daemon=True)
def configure_web_server():
    for web_server in settings['vms']['web_server']:
        vm_id = web_server['vm_id']
        pm_max_childs = web_server['pm_max_childs']
        mysql_server_vm_id = settings['vms']['mysql_server'][web_server['mysql_server']]['vm_id']
        memcache_server_vm_id = settings['vms']['memcache_server'][web_server['memcache_server']]['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker start -dt --net=host --name=web_server_%s cloudsuite/web-serving:web_server "
                    "/etc/bootstrap.sh mysql_server_%s memcache_server_%s %s"
                   % (vm_id, mysql_server_vm_id, memcache_server_vm_id, pm_max_childs))


@process.spawn(daemon=True)
def configure_faban_client():
    for faban_client in settings['vms']['faban_client']:
        vm_id = faban_client['vm_id']
        steady_state = faban_client['steady_state']
        pve.vm_is_ready(vm_id)
        for client_id in faban_client['clients']:
            pve.vm_run(vm_id,
                        "sudo docker start -dt --net none --name faban_client_%s --entrypoint bash cloudsuite/web-serving:faban_client"
                       % (client_id,))
            pve.vm_run(vm_id,
                        "sudo ./pipework/pipework br0 -i eth0 faban_client_%s 10.10.10.%s/24"
                       % (client_id, client_id))
            pve.vm_run(vm_id,
                        "sudo docker exec faban_client_%s sudo sed -i 's/<fa:steadyState>30/<fa:steadyState>%s/g' /etc/bootstrap.sh"
                       % (client_id, steady_state))


@process.spawn(daemon=True)
def configure_lb_server():
    for lb_server in settings['vms']['lb_server']:
        vm_id = lb_server['vm_id']
        policy = lb_server['policy']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id, "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy")
        pve.vm_run(vm_id,
                    "echo 'frontend web-serving\n    bind 10.10.10.%s:8080\n    default_backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg;"
                    "echo 'backend web-serving-backend\n    balance %s' | sudo tee -a /etc/haproxy/haproxy.cfg"
                   % (vm_id, policy))
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = settings['vms']['web_server'][web_server_id]['vm_id']
            pve.vm_run(vm_id,
                        "echo '    server web_server_%s 10.10.10.%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg"
                       % (web_server_vm_id, web_server_vm_id))
        pve.vm_run(vm_id, "sudo service haproxy stop")
        pve.vm_run(vm_id, "sudo service haproxy start")


def configure():
    run_mysql = configure_mysql_server()
    run_memcache = configure_memcache_server()
    run_web = configure_web_server()
    run_faban = configure_faban_client()
    run_lb = configure_lb_server()

    run_mysql.join()
    run_memcache.join()
    run_web.join()
    run_faban.join()
    run_lb.join()


@process.spawn(daemon=True)
def run_faban_client(vm_id, client_id, web_server_vm_id, load_scale):
    fab.local("rm -f results/faban_client_%s.log" % (client_id,))
    pve.vm_run(vm_id,
                "sudo docker exec faban_client_%s /etc/bootstrap.sh 10.10.10.%s %s"
               % (client_id, web_server_vm_id, load_scale),
                "/tmp/faban_client_%s.log" % (client_id,))
    fab.get("/tmp/faban_client_%s.log" % (client_id,), "results/")
    fab.run("rm -f /tmp/faban_client_%s.log" % (client_id,))


def run():
    runs = []
    for faban_client in settings['vms']['faban_client']:
        vm_id = faban_client['vm_id']
        load_scale = faban_client['load_scale']
        lb_server_vm_id = settings['vms']['lb_server'][faban_client['lb_server']]['vm_id']
        for client_id in faban_client['clients']:
            runs.append({
                'start': run_faban_client(vm_id, client_id, lb_server_vm_id, load_scale),
                'client_id': client_id})
    for i in range(len(runs)):
        runs[i]['start'].join()
        print 'faban_client_%s' % (runs[i]['client_id'],) + str(
            results.clean_results('results/faban_client_%s.log' % (runs[i]['client_id'],)))


def clear_mysql_server():
    for mysql_server in settings['vms']['mysql_server']:
        vm_id = mysql_server['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker stop mysql_server_%s;"
                    "sudo docker rm mysql_server_%s" % (vm_id, vm_id))


def clear_memcache_server():
    for memcache_server in settings['vms']['memcache_server']:
        vm_id = memcache_server['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker stop memcache_server_%s;"
                    "sudo docker rm memcache_server_%s" % (vm_id, vm_id))


def clear_web_server():
    for web_server in settings['vms']['web_server']:
        vm_id = web_server['vm_id']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo docker stop web_server_%s;"
                    "sudo docker rm web_server_%s" % (vm_id, vm_id))


def clear_lb_server():
    for lb_server in settings['vms']['lb_server']:
        vm_id = lb_server['vm_id']
        policy = lb_server['policy']
        pve.vm_is_ready(vm_id)
        pve.vm_run(vm_id,
                    "sudo sed --in-place '/frontend web-serving/d' /etc/haproxy/haproxy.cfg;"
                    "sudo sed --in-place '/bind 10.10.10.%s:8080/d' /etc/haproxy/haproxy.cfg;"
                    "sudo sed --in-place '/default_backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;"
                    "sudo sed --in-place '/backend web-serving-backend/d' /etc/haproxy/haproxy.cfg;"
                    "sudo sed --in-place '/balance %s/d' /etc/haproxy/haproxy.cfg"
                   % (vm_id, policy))
        for web_server_id in lb_server['web_servers']:
            web_server_vm_id = settings['vms']['web_server'][web_server_id]['vm_id']
            pve.vm_run(vm_id,
                        "sudo sed --in-place '/server web_server_%s 10.10.10.%s:8080/d' /etc/haproxy/haproxy.cfg"
                       % (web_server_vm_id, web_server_vm_id))
        pve.vm_run(vm_id, "sudo service haproxy stop")


def clear_faban_client(vm_id):
    pve.vm_run(vm_id,
                "sudo docker stop faban_client_%s;"
                "sudo docker rm faban_client_%s" % (vm_id, vm_id))


def clear():
    clear_mysql_server()
    clear_memcache_server()
    clear_web_server()
    clear_lb_server()
    for faban_client in settings['vms']['faban_client']:
        vm_id = faban_client['vm_id']
        clear_faban_client(vm_id)

