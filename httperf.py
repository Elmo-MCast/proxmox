# from pebble import process
from datetime import datetime
import json
import fabric.api as fab
import pve

""" Configurations """

fab.env.hosts = ['root@128.112.168.26', 'root@128.112.168.28']
fab.env['hostnames'] = ['mshahbaz-poweredge-1-pve', 'mshahbaz-poweredge-3-pve']
fab.env.roledefs = {
    'client': ['root@128.112.168.26'],
    'analyst': ['root@128.112.168.28']
}
fab.env['analyst_path'] = '/root/mshahbaz/notebooks/baseerat/runs'

""" 'httperf' settings """

with open("httperf.json") as json_file:
    settings = json.load(json_file)

""" 'httperf' Commands"""


@fab.roles('client')
def generate_client(base_vm_id, vm_id):
    pve.generate_vm(base_vm_id, vm_id, 'feedbackd-client' + str(vm_id), True)


@fab.roles('client')
def destroy_client(vm_id):
    pve.destroy_vm(vm_id)


@fab.roles('client')
def configure_client(base_vm_id, vm_id):
    pve.ssh_run(vm_id,
                "sudo sed -i 's/address 12.12.12.%s/address 12.12.12.%s/g' /etc/network/interfaces"
                % (base_vm_id, vm_id))
    pve.ssh_run(vm_id, "sudo apt-get install git")
    pve.ssh_run(vm_id, "git clone https://github.com/mshahbaz/httperf.git")
    pve.ssh_run(vm_id, "cd ~/httperf;autoreconf -i;./configure;make;sudo make install;cd ~/")
    pve.ssh_run(vm_id, "git clone https://github.com/mshahbaz/httperf-plot.git")
    pve.sync_vm(vm_id)
    pve.reboot_vm(vm_id)
    pve.is_vm_ready(vm_id)


@fab.roles('client')
def setup_clients():
    for vm_id in settings['vms']['clients']:
        generate_client(settings['vms']['base_vm_id'], vm_id)
        configure_client(settings['vms']['base_vm_id'], vm_id)

        if 'DR' in settings['vms']['type']:
            pve.add_route(vm_id, settings['vms']['type']['DR']['prefix'], settings['vms']['type']['DR']['iface'])


@fab.roles('client')
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


@fab.roles('client')
def is_client_rdy(vm_id):
    if int(pve.ssh_run(vm_id, 'netstat -t | wc -l')) > 100:
        fab.abort("too many TCP connections opened at client:%s" % (vm_id,))


@fab.roles('client')
def are_clients_rdy():
    for vm_id in settings['vms']['clients']:
        is_client_rdy(vm_id)


@fab.roles('client')
def pre_run_httperf_client(vm_id):
    httperf_script = "cd ~/httperf-plot; " \
                     "python httperf-plot.py --server %s --port %s " \
                     "--hog --verbose --num-conns %s --num-calls %s --rate %s " \
                     "--ramp-up %s,%s --timeout %s " \
                     "--csv %s > %s; " \
                     "cd ~/" \
                     % (settings['httperf']['vip'], settings['httperf']['port'],
                        settings['httperf']['num-conns'], settings['httperf']['num-calls'], settings['httperf']['rate'],
                        settings['httperf']['ramp'], settings['httperf']['iters'], settings['httperf']['timeout'],
                        "httperf_client_%s.csv" % (vm_id,),
                        "httperf_client_%s.log" % (vm_id,))
    pve.ssh_run(vm_id, "echo '" + httperf_script + "' > ~/httperf_script.sh")


@fab.roles('client')
def pre_run_httperf_clients():
    for vm_id in settings['vms']['clients']:
        pre_run_httperf_client(vm_id)


@fab.roles('client')
def post_run_httperf_client(vm_id, datetime_str):
    pve.scp_get(vm_id, "~/httperf-plot/httperf_client_%s.*" % (vm_id,), "/tmp/")
    fab.run("sshpass -p " + fab.env.password +
            " scp -o 'StrictHostKeyChecking no' /tmp/httperf_client_%s.* " % (vm_id,) +
            fab.env.roledefs['analyst'][0] + ":" + fab.env['analyst_path'] + "/" + datetime_str + "/")
    pve.ssh_run(vm_id, "rm -f ~/httperf-plot/httperf_client_%s.* ~/httperf_script.sh"
                % (vm_id,))
    fab.run("rm -f /tmp/httperf_client_%s.*" % (vm_id,))


@fab.roles('client')
def post_run_httperf_clients():
    datetime_str = str(datetime.now()).replace(':', '.').replace(' ', '.')
    fab.run("sshpass -p " + fab.env.password +
            " ssh -o 'StrictHostKeyChecking no' " + fab.env.roledefs['analyst'][0] +
            " 'mkdir " + fab.env['analyst_path'] + "/" + datetime_str + "'")
    for vm_id in settings['vms']['clients']:
        post_run_httperf_client(vm_id, datetime_str)


@fab.roles('client')
def run_httperf_clients():
    pve.parallel_ssh_run({vm_id: "sh ~/httperf_script.sh" for vm_id in settings['vms']['clients']})


@fab.roles('client')
def run():
    are_clients_rdy()
    pre_run_httperf_clients()
    run_httperf_clients()
    post_run_httperf_clients()


@fab.roles('client')
def clean_httperf_client():
    pve.parallel_ssh_run({vm_id: "sudo skill httperf" for vm_id in settings['vms']['clients']})


@fab.roles('client')
def clean():
    clean_httperf_client()
