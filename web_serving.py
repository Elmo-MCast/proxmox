
import pve


vm_ids = {
    'db_server': 204,
    'web_server': 205,
    'memcached_server': 206,
    'faban_client': 207
}

pm_max_childs = 150
load_scale = 100


def configure_db_server(vm_id, web_server_id):
    pve.is_vm_ready(vm_id)
    pve.ssh_run(vm_id, "curl -sSL https://get.docker.com/ | sh")
    pve.ssh_run(vm_id, "sudo docker pull cloudsuite/web-serving:db_server")
    pve.ssh_run(vm_id,
                "sudo docker run -dt --net host --name db_server_%s cloudsuite/web-serving:db_server web_server_%s"
                % (vm_id, web_server_id))


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


def run_faban_client(vm_id, web_server_id, load_scale):
    pve.ssh_run(vm_id,
                "sudo docker run --net host --name faban_client_%s "
                "cloudsuite/web-serving:faban_client 10.10.10.%s %s"
                % (vm_id, web_server_id, load_scale))


def clear_faban_client(vm_id):
    pve.ssh_run(vm_id,
                "sudo docker stop faban_client_%s;"
                "sudo docker rm faban_client_%s"
                % (vm_id, vm_id))


def add_hosts():
    for vm_id in vm_ids.values():
        for server_name, server_id in vm_ids.iteritems():
            pve.add_host(vm_id, server_id, "%s_%s" % (server_name, server_id))


def generate():
    pve.generate_vms('web-serving', *vm_ids.values())
    add_hosts()


def destroy():
    pve.destroy_vms(*vm_ids.values())


def configure():
    configure_db_server(vm_ids['db_server'], vm_ids['web_server'])
    configure_memcached_server(vm_ids['memcached_server'])
    configure_web_server(vm_ids['web_server'], vm_ids['db_server'], vm_ids['memcached_server'], pm_max_childs)
    configure_faban_client(vm_ids['faban_client'])


def run():
    run_faban_client(vm_ids['faban_client'], vm_ids['web_server'], load_scale)


def clear():
    clear_faban_client(vm_ids['faban_client'])


def all():
    generate()
    configure()
    run()