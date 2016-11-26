from pebble import process
import fabric.api as fab
import pve
import results

# Settings

settings = {
    'vms': {
        'mysql_server': [
            {'vm_id': 207, 'web_server': 0}
        ],
        'memcache_server': [
            {'vm_id': 207}
        ],
        'web_server': [
            {'vm_id': 207, 'pm_max_childs': 80, 'mysql_server': 0, 'memcache_server': 0}
        ],
        'faban_client': [
            {'vm_id': 208, 'load_scale': 7, 'web_server': 0}
        ]
    },
    'vm_prefix': 'web-serving',
    'base_vm_id': 197
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
            pve.add_host(vm_id, server_vm_id, server_name)


def generate():
    pve.generate_vms(settings['base_vm_id'], settings['vm_prefix'], *vm_id_list)
    add_hosts()


def destroy():
    pve.destroy_vms(*vm_id_list)



# def configure_common():
#     for vm_id in vm_id_list:
#         pve.is_vm_ready(vm_id)
#         pve.ssh_run(vm_id,
#                     "sudo apt-get update;"
#                     "curl -sSL https://get.docker.com/ | sh;"
#                     "sudo apt-get install haproxy;"
#                     "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy")


@process.spawn(daemon=True)
def configure_mysql_server():
    for mysql_server in settings['vms']['mysql_server']:
        vm_id = mysql_server['vm_id']
        web_server_vm_id = settings['vms']['web_server'][mysql_server['web_server']]['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker run -dt --net host --name mysql_server_%s cloudsuite/web-serving:db_server 10.10.10.%s"
                    % (vm_id, web_server_vm_id,))


@process.spawn(daemon=True)
def configure_memcache_server():
    for memcache_server in settings['vms']['memcache_server']:
        vm_id = memcache_server['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker run -dt --net=host --name=memcache_server_%s cloudsuite/web-serving:memcached_server"
                    % (vm_id,))


@process.spawn(daemon=True)
def configure_web_server():
    for web_server in settings['vms']['web_server']:
        vm_id = web_server['vm_id']
        pm_max_childs = web_server['pm_max_childs']
        mysql_server_vm_id = settings['vms']['mysql_server'][web_server['mysql_server']]['vm_id']
        memcache_server_vm_id = settings['vms']['memcache_server'][web_server['memcache_server']]['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker run -dt --net=host --name=web_server_%s cloudsuite/web-serving:web_server "
                    "/etc/bootstrap.sh mysql_server_%s memcache_server_%s %s"
                    % (vm_id, mysql_server_vm_id, memcache_server_vm_id, pm_max_childs))


def configure():
    run_mysql = configure_mysql_server()
    run_memcache = configure_memcache_server()
    run_web = configure_web_server()

    run_mysql.join()
    run_memcache.join()
    run_web.join()


@process.spawn(daemon=True)
def run_faban_client(vm_id, web_server_vm_id, load_scale):
    fab.local('rm -f results/faban_client_%s.log' % (vm_id,))
    pve.ssh_run(vm_id,
                "sudo docker run --net host --name faban_client_%s cloudsuite/web-serving:faban_client 10.10.10.%s %s"
                % (vm_id, web_server_vm_id, load_scale),
                "/tmp/faban_client_%s.log" % (vm_id,))
    fab.get("/tmp/faban_client_%s.log" % (vm_id,), "results/")
    fab.run("rm -f /tmp/faban_client_%s.log" % (vm_id,))


def run():
    runs = []
    for faban_client in settings['vms']['faban_client']:
        vm_id = faban_client['vm_id']
        load_scale = faban_client['load_scale']
        web_server_vm_id = settings['vms']['web_server'][faban_client['web_server']]['vm_id']
        runs.append({
            'run': run_faban_client(vm_id, web_server_vm_id, load_scale),
            'vm_id': vm_id})
    for i in range(len(runs)):
        runs[i]['run'].join()
        print results.clean_results('results/faban_client_%s.log' % (runs[i]['vm_id'],))


@process.spawn(daemon=True)
def clear_mysql_server():
    for mysql_server in settings['vms']['mysql_server']:
        vm_id = mysql_server['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker stop mysql_server_%s;"
                    "sudo docker rm mysql_server_%s" % (vm_id, vm_id))


@process.spawn(daemon=True)
def clear_memcache_server():
    for memcache_server in settings['vms']['memcache_server']:
        vm_id = memcache_server['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker stop memcache_server_%s;"
                    "sudo docker rm memcache_server_%s" % (vm_id, vm_id))


@process.spawn(daemon=True)
def clear_web_server():
    for web_server in settings['vms']['web_server']:
        vm_id = web_server['vm_id']
        pve.is_vm_ready(vm_id)
        pve.ssh_run(vm_id,
                    "sudo docker stop web_server_%s;"
                    "sudo docker rm web_server_%s" % (vm_id, vm_id))


@process.spawn(daemon=True)
def clear_faban_client(vm_id):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id,
                "sudo docker stop faban_client_%s;"
                "sudo docker rm faban_client_%s" % (vm_id, vm_id))


def clear():
    run_mysql = clear_mysql_server()
    run_memcache = clear_memcache_server()
    run_web = clear_web_server()
    runs = []
    for faban_client in settings['vms']['faban_client']:
        vm_id = faban_client['vm_id']
        runs.append(clear_faban_client(vm_id))

    run_mysql.join()
    run_memcache.join()
    run_web.join()
    for i in range(len(runs)):
        runs[i].join()
