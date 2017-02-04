import os
import json
from datetime import datetime
import fabric.api as fab

from common import pve

""" Configurations """

with open(os.path.dirname(__file__) + "/httperf.json") as json_file:
    settings = json.load(json_file)

fab.env.warn_only = settings['env']['warn_only']
fab.env.hosts = settings['env']['hosts']
fab.env.roledefs = settings['env']['roledefs']
fab.env.user = settings['env']['user']
fab.env.password = settings['env']['password']
fab.env['vm'] = settings['env']['vm']
fab.env['analyst'] = settings['env']['analyst']

fab.env['httperf'] = settings['httperf']

""" 'httperf' Commands"""


@fab.roles('client')
def setup_scripts():
    scripts = list()
    # Install common apps
    script = "sudo apt-get -y install git; " \
             "git clone https://github.com/mshahbaz/httperf.git; " \
             "cd ~/httperf; autoreconf -i; ./configure; make; sudo make install; cd ~/; " \
             "git clone https://github.com/mshahbaz/httperf-plot.git; "
    # Network configs
    if fab.env['httperf']['lb']['ipvs']['enable']:
        if fab.env['httperf']['lb']['ipvs']['type']['DR']['enable']:
            script += "sudo ip route add %s dev %s; " \
                      % (fab.env['httperf']['lb']['ipvs']['type']['DR']['prefix'],
                         fab.env['httperf']['lb']['ipvs']['type']['DR']['iface'])
        elif fab.env['httperf']['lb']['ipvs']['type']['NAT']['enable']:
            pass
    elif fab.env['httperf']['lb']['haproxy']['enable']:
        raise Exception("'haproxy' isn't supported yet")
    scripts.append("echo '%s' > ~/setup_script.sh; " % (script,))
    scripts.append("sh ~/setup_script.sh; ")
    return scripts


@fab.roles('client')
def setup():
    pve.vm_generate_multi(fab.env['httperf']['vm']['base_id'], "httperf-client", True, setup_scripts(),
                          *fab.env['httperf']['vm']['clients'])


@fab.roles('client')
def cleanup():
    pve.vm_destroy_multi(*fab.env['httperf']['vm']['clients'])


# @process.spawn(daemon=True)
# def run_httperf_client(vm_id):
#     if int(pve.vm_run(vm_id, 'netstat -t | wc -l')) > 100:
#         fab.abort("too many TCP connections opened at client:%s" % (vm_id,))
#     fab.local('rm -f results/httperf_client_%s.log' % (vm_id,))
#     fab.local('rm -f results/httperf_client_%s.csv' % (vm_id,))
#     pve.vm_run(vm_id,
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
#     pve.vm_get(vm_id,
#                 "~/httperf-plot/%s" % (settings['httperf']['csv-file'],), "/tmp/httperf_client_%s.csv" % (vm_id,))
#     fab.get("/tmp/httperf_client_%s.log" % (vm_id,), "results/")
#     fab.get("/tmp/httperf_client_%s.csv" % (vm_id,), "results/")
#     pve.vm_run(vm_id, "rm -f ~/httperf-plot/%s" % (settings['httperf']['csv-file'],))
#     fab.start("rm -f /tmp/httperf_client_%s.log" % (vm_id,))
#     fab.start("rm -f /tmp/httperf_client_%s.csv" % (vm_id,))


@fab.roles('client')
def client_is_ready(vm_id):
    if int(pve.vm_run(vm_id, 'netstat -t | wc -l')) > 100:
        fab.abort("too many TCP connections opened at client:%s" % (vm_id,))


@fab.roles('client')
def clients_are_ready():
    for vm_id in fab.env['httperf']['vm']['clients']:
        client_is_ready(vm_id)


@fab.roles('client')
def client_pre_httperf_run(vm_id):
    script = "cd ~/httperf-plot; " \
             "python httperf-plot.py --server %s --port %s " \
             "--hog --verbose --num-conns %s --num-calls %s --rate %s " \
             "--ramp-up %s,%s --timeout %s " \
             "--csv %s > %s; " \
             "cd ~/; " \
             % (fab.env['httperf']['cfg']['vip'], fab.env['httperf']['cfg']['port'],
                fab.env['httperf']['cfg']['num-conns'], fab.env['httperf']['cfg']['num-calls'],
                fab.env['httperf']['cfg']['rate'], fab.env['httperf']['cfg']['ramp'],
                fab.env['httperf']['cfg']['iters'], fab.env['httperf']['cfg']['timeout'],
                "httperf_client_%s.csv" % (vm_id,),
                "httperf_client_%s.log" % (vm_id,))
    return "echo '%s' > ~/httperf_script.sh; " \
           % (script,)


@fab.roles('client')
def pre_httperf_run():
    scripts = dict()
    for vm_id in fab.env['httperf']['vm']['clients']:
        scripts[vm_id] = client_pre_httperf_run(vm_id)
    pve.vm_parallel_run(scripts)


@fab.roles('client')
def client_post_httperf_run(vm_id, datetime_str):
    pve.vm_get(vm_id, "~/httperf-plot/httperf_client_%s.*" % (vm_id,), "/tmp/")
    fab.run("sshpass -p %s scp /tmp/httperf_client_%s.* %s:%s/%s/"
            % (fab.env.password, vm_id, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
    pve.vm_run(vm_id, "rm -f ~/httperf-plot/httperf_client_%s.* ~/httperf_script.sh" % (vm_id,))
    fab.run("rm -f /tmp/httperf_client_%s.*" % (vm_id,))


@fab.roles('client')
def post_httperf_run():
    datetime_str = str(datetime.now()).replace(':', '.').replace(' ', '.')
    fab.run("sshpass -p %s ssh %s 'mkdir %s/%s'"
            % (fab.env.password, fab.env.roledefs['analyst'][0], fab.env['analyst']['path'], datetime_str))
    for vm_id in fab.env['httperf']['vm']['clients']:
        client_post_httperf_run(vm_id, datetime_str)


@fab.roles('client')
def httperf_run():
    pve.vm_parallel_run({vm_id: "sh ~/httperf_script.sh" for vm_id in fab.env['httperf']['vm']['clients']})


@fab.roles('client')
def start():
    clients_are_ready()
    pre_httperf_run()
    httperf_run()
    post_httperf_run()


@fab.roles('client')
def stop_httperf_run():
    pve.vm_parallel_run({vm_id: "sudo skill httperf" for vm_id in fab.env['httperf']['vm']['clients']})


@fab.roles('client')
def stop():
    stop_httperf_run()
