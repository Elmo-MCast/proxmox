from pebble import process
import fabric.api as fab
import pve

print fab.env.hosts

fab.env.hosts = ['128.112.168.26']
fab.env.user = 'root'
fab.env.password = 'PrincetonP4OVS1'
fab.env.warn_only = True
fab.env["poweredge_name"] = 'mshahbaz-poweredge-1-pve'
# fab.env['vm_ssh_key'] = '/root/ssh/httperf_id_rsa'
fab.env['vm_ssh_passwd'] = 'nopass'


# Settings


settings = {
    'vms': {
        'base_vm_id': 105,
        # 'clients': [110],
        'clients': [110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125],
        # 'type': 'NAT'
        'type': {
            'DR': {
                'prefix': '172.17.60.0/24',
                'iface': 'eth1'
            }
        }
    },
    'httperf': {
        'vip': '172.17.60.201',
        'port': 80,
        'num-conns': 2000,
        'num-calls': 1,
        'rate': 20,
        'ramp': 20,
        'iters': 2,
        'timeout': 1
    }
}


def generate_client(base_vm_id, vm_id):
    pve.generate_vm(base_vm_id, vm_id, 'feedbackd-client'+str(vm_id), True)


def destroy_client(vm_id):
    pve.destroy_vm(vm_id)


def configure_client(base_vm_id, vm_id):
    pve.ssh_run(vm_id,
                "sudo sed -i 's/address 12.12.12.%s/address 12.12.12.%s/g' /etc/network/interfaces"
                % (base_vm_id, vm_id))
    pve.ssh_run(vm_id, "sudo apt-get install git httperf")
    pve.ssh_run(vm_id, "git clone https://github.com/mshahbaz/httperf-plot.git")
    pve.sync_vm(vm_id)
    pve.reboot_vm(vm_id)
    pve.is_vm_ready(vm_id)


def setup_clients():
    for vm_id in settings['vms']['clients']:
        generate_client(settings['vms']['base_vm_id'], vm_id)
        configure_client(settings['vms']['base_vm_id'], vm_id)

        if 'DR' in settings['vms']['type']:
            pve.add_route(vm_id, settings['vms']['type']['DR']['prefix'], settings['vms']['type']['DR']['iface'])


def destroy_clients():
    for vm_id in settings['vms']['clients']:
        destroy_client(vm_id)


# @process.spawn(daemon=True)
# def run_httperf_client(vm_id):
#     if int(pve.ssh_run(vm_id, 'netstat -t | wc -l')) > 100:
#         fab.abort("too many TCP connections opened at client:%s" % (vm_id,))
#     fab.local('rm -f results/httperf_client_%s.log' % (vm_id,))
#     fab.local('rm -f results/httperf_client_%s.csv' % (vm_id,))
#     pve.ssh_run(vm_id,
#                 "cd ~/httperf-plot;"
#                 "python httperf-plot.py --server %s --port %s "
#                 "--hog --num-conns %s --num-calls %s --rate %s "
#                 "--ramp-up %s,%s --timeout %s "
#                 "--csv %s;"
#                 "cd ~/"
#                 % (settings['httperf']['vip'], settings['httperf']['port'],
#                    settings['httperf']['num-conns'], settings['httperf']['num-calls'], settings['httperf']['rate'],
#                    settings['httperf']['ramp'], settings['httperf']['iters'], settings['httperf']['timeout'],
#                    settings['httperf']['csv-file']),
#                 "/tmp/httperf_client_%s.log" % (vm_id,))
#     pve.scp_get(vm_id,
#                 "~/httperf-plot/%s" % (settings['httperf']['csv-file'],), "/tmp/httperf_client_%s.csv" % (vm_id,))
#     fab.get("/tmp/httperf_client_%s.log" % (vm_id,), "results/")
#     fab.get("/tmp/httperf_client_%s.csv" % (vm_id,), "results/")
#     pve.ssh_run(vm_id, "rm -f ~/httperf-plot/%s" % (settings['httperf']['csv-file'],))
#     fab.run("rm -f /tmp/httperf_client_%s.log" % (vm_id,))
#     fab.run("rm -f /tmp/httperf_client_%s.csv" % (vm_id,))


def is_client_rdy(vm_id):
    if int(pve.ssh_run(vm_id, 'netstat -t | wc -l')) > 100:
        fab.abort("too many TCP connections opened at client:%s" % (vm_id,))


def are_clients_rdy():
    for vm_id in settings['vms']['clients']:
        is_client_rdy(vm_id)


def pre_run_httperf_client(vm_id):
    fab.local('rm -f results/httperf_client_%s.log; rm -f results/httperf_client_%s.csv' % (vm_id, vm_id))

    httperf_script = "cd ~/httperf-plot;" \
                     "python httperf-plot.py --server %s --port %s " \
                     "--hog --num-conns %s --num-calls %s --rate %s " \
                     "--ramp-up %s,%s --timeout %s " \
                     "--csv %s > %s;" \
                     "cd ~/" \
                     % (settings['httperf']['vip'], settings['httperf']['port'],
                        settings['httperf']['num-conns'], settings['httperf']['num-calls'], settings['httperf']['rate'],
                        settings['httperf']['ramp'], settings['httperf']['iters'], settings['httperf']['timeout'],
                        "httperf_client_%s.csv" % (vm_id,),
                        "httperf_client_%s.log" % (vm_id,))
    pve.ssh_run(vm_id, "echo '" + httperf_script + "' > ~/httperf_script.sh")


def pre_run_httperf_clients():
    for vm_id in settings['vms']['clients']:
        pre_run_httperf_client(vm_id)


def post_run_httperf_client(vm_id):
    pve.scp_get(vm_id, "~/httperf-plot/httperf_client_%s.csv" % (vm_id,), "/tmp/httperf_client_%s.csv" % (vm_id,))
    pve.scp_get(vm_id, "~/httperf-plot/httperf_client_%s.log" % (vm_id,), "/tmp/httperf_client_%s.log" % (vm_id,))
    fab.get("/tmp/httperf_client_%s.csv" % (vm_id,), "results/")
    fab.get("/tmp/httperf_client_%s.log" % (vm_id,), "results/")
    pve.ssh_run(vm_id, "rm -f ~/httperf-plot/httperf_client_%s.csv; rm -f ~/httperf-plot/httperf_client_%s.log"
                       "rm -f ~/httperf_script.sh"
                % (vm_id, vm_id))
    fab.run("rm -f /tmp/httperf_client_%s.csv; rm -f /tmp/httperf_client_%s.log" % (vm_id, vm_id))


def post_run_httperf_clients():
    for vm_id in settings['vms']['clients']:
        post_run_httperf_client(vm_id)


def run_httperf_clients():
    pve.parallel_run({vm_id: "sh ~/httperf_script.sh" for vm_id in settings['vms']['clients']})


def run():
    are_clients_rdy()
    pre_run_httperf_clients()
    run_httperf_clients()
    post_run_httperf_clients()


def clean_httperf_client():
    for vm_id in settings['vms']['clients']:
        pve.ssh_run(vm_id, 'sudo skill httperf')


def clean():
    clean_httperf_client()
