
from pebble import process
from fabric.api import *
import pve
import results

vm_ids = {
    'lb_server': 203,
    'db_server': [
        204,
        205
    ],
    'web_server': [
        206,
        207
    ],
    'memcached_server': [
        208,
        209
    ],
    'faban_client': [
        210,
        211
    ]
}

pm_max_childs = 150
load_scale = 10

assert (len(vm_ids['db_server']) == len(vm_ids['web_server']) and
        len(vm_ids['web_server']) == len(vm_ids['memcached_server']))

num_backends = len(vm_ids['web_server'])
num_clients = len(vm_ids['faban_client'])

ids = dict()
ids['lb_server_%s' % (vm_ids['lb_server'],)] = vm_ids['lb_server']
for i in vm_ids['db_server']:
    ids['db_server_%s' % (i,)] = i
for i in vm_ids['web_server']:
    ids['web_server_%s' % (i,)] = i
for i in vm_ids['memcached_server']:
    ids['memcached_server_%s' % (i,)] = i
for i in vm_ids['faban_client']:
    ids['faban_client_%s' % (i,)] = i


def configure_db_server(vm_id, lb_server_id):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id, "curl -sSL https://get.docker.com/ | sh")
    pve.ssh_run(vm_id, "sudo docker pull cloudsuite/web-serving:db_server")
    pve.ssh_run(vm_id,
                "sudo docker run -dt --net host --name db_server_%s cloudsuite/web-serving:db_server lb_server_%s"
                % (vm_id, lb_server_id))
    # TODO: this maybe incorrect


def configure_web_server(vm_id, db_server_id, memcached_server_id, pm_max_childs):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id, "curl -sSL https://get.docker.com/ | sh")
    pve.ssh_run(vm_id, "sudo docker pull cloudsuite/web-serving:web_server")
    pve.ssh_run(vm_id,
                "sudo docker run -dt --net host --name web_server_%s cloudsuite/web-serving:web_server "
                "/etc/bootstrap.sh db_server_%s memcached_server_%s %s"
                % (vm_id, db_server_id, memcached_server_id, pm_max_childs))


def configure_memcached_server(vm_id):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id, "curl -sSL https://get.docker.com/ | sh")
    pve.ssh_run(vm_id, "sudo docker pull cloudsuite/web-serving:memcached_server")
    pve.ssh_run(vm_id,
                "sudo docker run -dt --net host --name memcached_server_%s cloudsuite/web-serving:memcached_server"
                % (vm_id,))


def configure_faban_client(vm_id):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id, "curl -sSL https://get.docker.com/ | sh")
    pve.ssh_run(vm_id, "sudo docker pull cloudsuite/web-serving:faban_client")


def configure_lb_server(vm_id, web_server_ids):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(
        vm_id,
        "sudo apt-get update;"
        "sudo apt-get install haproxy;"
        "sudo sed -i 's/ENABLED=0/ENABLED=1/g' /etc/default/haproxy;"
        "echo 'frontend web-serving\n    bind 10.10.10.%s:8080\n    default_backend web-serving-backend' | sudo tee -a /etc/haproxy/haproxy.cfg;"
        "echo 'backend web-serving-backend\n    balance source' | sudo tee -a /etc/haproxy/haproxy.cfg;"
        % (vm_id,))
    for web_server_id in web_server_ids:
        pve.ssh_run(
            vm_id,
            "echo '    server web_server_%s 10.10.10.%s:8080' | sudo tee -a /etc/haproxy/haproxy.cfg;"
            % (web_server_id, web_server_id))
    pve.ssh_run(
        vm_id,
        "sudo service haproxy restart")


@process.spawn(daemon=True)
def run_faban_client(vm_id, web_server_id, load_scale):
    local('rm -f results/faban_client_%s.log' % (vm_id,))
    pve.ssh_run(vm_id,
                "sudo docker run --net host --name faban_client_%s "
                "cloudsuite/web-serving:faban_client 10.10.10.%s %s"
                % (vm_id, web_server_id, load_scale),
                "/tmp/faban_client_%s.log" % (vm_id,))
    get("/tmp/faban_client_%s.log" % (vm_id,), "results/")


def clear_faban_client(vm_id):
    pve.ssh_run(vm_id,
                "sudo docker stop faban_client_%s;"
                "sudo docker rm faban_client_%s"
                % (vm_id, vm_id))


def add_hosts(vm_ids):
    for vm_id in vm_ids.values():
        for server_name, server_id in vm_ids.iteritems():
            pve.add_host(vm_id, server_id, "%s" % (server_name,))


def generate():
    pve.generate_vms('we-serving-haproxy', *ids.values())
    add_hosts(ids)


def destroy():
    pve.destroy_vms(*ids.values())


def configure():
    for i in range(num_backends):
        configure_db_server(vm_ids['db_server'][i], vm_ids['lb_server'])
        configure_memcached_server(vm_ids['memcached_server'][i])
        configure_web_server(vm_ids['web_server'][i], vm_ids['db_server'][i],
                             vm_ids['memcached_server'][i], pm_max_childs)
    for i in range(num_clients):
        configure_faban_client(vm_ids['faban_client'][i])
    configure_lb_server(vm_ids['lb_server'], vm_ids['web_server'])


def run():
    runs = []
    for i in range(num_clients):
        runs.append(run_faban_client(vm_ids['faban_client'][i], vm_ids['lb_server'], load_scale))
    for i in range(num_clients):
        runs[i].join()


def result():
    for i in range(num_clients):
        print 'faban_client_' + str(vm_ids['faban_client'][i]) + ": " + \
              str(results.clean_results('results/faban_client_%s.log' % (vm_ids['faban_client'][i],)))


def clear():
    for i in range(num_clients):
        clear_faban_client(vm_ids['faban_client'][i])

