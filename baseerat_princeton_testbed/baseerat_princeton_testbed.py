import json
import os
from datetime import datetime
from multiprocessing import Process
import fabric.api as fab
import time

from pve import pve
from helpers import results

""" Configurations """

with open(os.path.dirname(__file__) + "/" + os.path.basename(__file__).split('.')[0] + ".json") as json_file:
    settings = json.load(json_file)

fab.env.warn_only = settings['env']['warn_only']
fab.env.hosts = settings['env']['hosts']
fab.env.roledefs = settings['env']['roledefs']
fab.env.user = settings['env']['user']
fab.env.password = settings['env']['password']
fab.env['vm'] = settings['env']['vm']
fab.env['analyst'] = settings['env']['analyst']

fab.env['ovs'] = settings['ovs']
fab.env['pu-pve2'] = settings['pu-pve2']

""" Helper Functions """


def is_execute(execute):
    if isinstance(execute, str):
        if execute == "True":
            return True
        else:
            return False
    else:
        return execute


def _get_client_vm_id_list(vms):
    vm_id_set = set()
    for vm in vms:
        vm_id = vm['vm_id']
        vm_id_set |= {vm_id}
    return list(vm_id_set)


def _setup_options(vms, options):
    for vm in vms:
        vm_id = vm['vm_id']
        sockets = options['sockets']
        cores = options['cores']
        memory = options['memory']
        pve.vm_options(vm_id, 'sockets', sockets)
        pve.vm_options(vm_id, 'cores', cores)
        pve.vm_options(vm_id, 'memory', memory)
        pve.vm_stop(vm_id)
        pve.vm_start(vm_id)

    for vm in vms:
        pve.vm_is_ready(vm['vm_id'])


def _setup_ifaces(scripts, vms, settings, execute=True):
    if not isinstance(scripts, dict):
        scripts = dict()
    prefix_1 = settings['prefix_1']
    for vm in vms:
        vm_id = vm['vm_id']
        scripts[vm_id] = "sudo ip addr add %s%s/24 dev eth1; " \
                         "sudo ip link set eth1 up; " \
                         % (prefix_1, vm_id)
    if is_execute(execute):
        pve.vm_parallel_run(scripts)
    else:
        return scripts


""" 'baseerat_princeton_testbed' Commands """

''' Common OVS Commands '''


def ovs_start(cpu_mask=0x1, execute=True):
    var_path = fab.env['ovs']['paths']['var']
    ovsdb_path = fab.env['ovs']['paths']['base'] + "/ovsdb"
    vswitchd_path = fab.env['ovs']['paths']['base'] + "/vswitchd"
    script = "%s/ovsdb-server --remote=punix:%s/db.sock " \
             "--remote=db:Open_vSwitch,Open_vSwitch,manager_options --pidfile --detach; " \
             % (ovsdb_path, var_path,)
    script += "%s/ovs-vswitchd --dpdk -c %s -n 4 -- unix:%s/db.sock" \
              " --pidfile --detach; " % (vswitchd_path, cpu_mask, var_path)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_stop(execute=True):
    var_path = fab.env['ovs']['paths']['var']
    script = "kill `cat %s/ovsdb-server.pid`; " \
             "kill `cat %s/ovs-vswitchd.pid`; " % (var_path, var_path)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_add_port(bridge_name, port, execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    if port.startswith('dpdk'):
        script = "%s/ovs-vsctl add-port %s %s -- set Interface %s type=dpdk; " \
                 % (utilities_path, bridge_name, port, port)
    else:
        script = "%s/ovs-vsctl add-port %s %s; " \
                 % (utilities_path, bridge_name, port)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_delete_port(bridge_name, port, execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-vsctl del-port %s %s; " \
             % (utilities_path, bridge_name, port)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_add_bridge(name='br0', execute=True, *ports):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-vsctl add-br %s -- set bridge %s datapath_type=netdev; " \
             "%s/ovs-vsctl set bridge %s protocols=OpenFlow15; " \
             % (utilities_path, name, name,
                utilities_path, name)
    for port in ports:
        script += ovs_add_port(name, port, False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_delete_bridge(name='br0', execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-vsctl del-br %s; " \
             % (utilities_path, name)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_show_bridge(option='ofctl', bridge_name='br0', execute=True):  # options are: ofctl, vsctl
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    if option == 'ofctl':
        script = "%s/ovs-ofctl --protocols=OpenFlow15 show %s; " % (utilities_path, bridge_name)
        if is_execute(execute):
            fab.run(script)
        else:
            return script
    elif option == 'vsctl':
        script = "%s/ovs-vsctl show; " % (utilities_path)
        if is_execute(execute):
            fab.run(script)
        else:
            return script
    else:
        print('Invalid option (%s)' % (option,))


def ovs_dump_flows(bridge_name='br0', execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 dump-flows %s; " \
             % (utilities_path, bridge_name)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_delete_flows(bridge_name='br0', execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 del-flows %s; " \
             % (utilities_path, bridge_name)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def ovs_add_flow(bridge_name, flow_rule, execute=True):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 add-flow %s '%s'; " \
             % (utilities_path, bridge_name, flow_rule)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


''' Common pu-pve* Commands '''


def pve_clear_vswitch(bridge_name, ports, execute=True):
    script = ""
    for port in ports:
        script += ovs_delete_port(bridge_name, port, False)
    script += ovs_delete_bridge(bridge_name, False)
    script += ovs_stop(False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def pve_configure_vswitch(cpu_mask, bridge_name, ports, execute=True):
    script = ovs_stop(False)
    script += ovs_start(cpu_mask, False)
    for port in ports:
        script += ovs_delete_port(bridge_name, port, False)
    script += ovs_delete_bridge(bridge_name, False)
    script += ovs_add_bridge(bridge_name, False, *ports)
    script += ovs_delete_flows(bridge_name, False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def pve_connect_vswitch_to_bridge_1(bridge_name, bridge_1, execute=True):
    script = pve_disconnect_vswitch_from_bridge_1(bridge_name, bridge_1, False)
    script += "ip link add %s%si0 type veth peer name %s%si1; " \
              "ip link set dev %s%si0 up; ip link set dev %s%si1 up; " \
              "brctl addif %s %s%si0; " \
              % (bridge_name, bridge_1, bridge_name, bridge_1,
                 bridge_name, bridge_1, bridge_name, bridge_1,
                 bridge_1, bridge_name, bridge_1)
    script += ovs_add_port(bridge_name, "%s%si1" % (bridge_name, bridge_1), False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


def pve_disconnect_vswitch_from_bridge_1(bridge_name, bridge_1, execute=True):
    script = ovs_delete_port(bridge_name, "%s%si1" % (bridge_name, bridge_1), False)
    script += "brctl delif %s %s%si0; " \
              "ip link del %s%si0; " \
              % (bridge_1, bridge_name, bridge_1,
                 bridge_name, bridge_1)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


''' pu-pve2 (ToR and Clients) Commands '''


@fab.roles('pu-pve2')
def pve2_setup_vswitch():
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    ports = fab.env['pu-pve2']['bridge']['ports']
    bridge_1 = fab.env['pu-pve2']['settings']['vm']['bridge_1']
    script = pve_configure_vswitch(0x1, bridge_name, ports, False)
    script += pve_connect_vswitch_to_bridge_1(bridge_name, bridge_1, False)
    script += ovs_show_bridge('ofctl', bridge_name, False)
    fab.run(script)


@fab.roles('pu-pve2')
def pve2_cleanup_vswitch():
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    ports = fab.env['pu-pve2']['bridge']['ports']
    bridge_1 = fab.env['pu-pve2']['settings']['vm']['bridge_1']
    script = pve_disconnect_vswitch_from_bridge_1(bridge_name, bridge_1, False)
    script += pve_clear_vswitch(bridge_name, ports, False)
    fab.run(script)


@fab.roles('pu-pve2')
def pve2_configure_flow_rules():
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    flow_rules = fab.env['pu-pve2']['bridge']['flow_rules']
    script = ""
    for flow_rule in flow_rules:
        script += ovs_add_flow(bridge_name, flow_rule, False)
    fab.run(script)
    # TODO: come up with right rules for the client VMs.


@fab.roles('pu-pve2')
def pve2_clear_flow_rules():
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    return ovs_delete_flows(bridge_name, True)


@fab.roles('pu-pve2')
def pve2_setup_clients():
    pve.vm_generate_multi(fab.env['pu-pve2']['settings']['vm']['base_id'], 'client', False, None,
                          *_get_client_vm_id_list(fab.env['pu-pve2']['clients']['vms']))
    _setup_options(fab.env['pu-pve2']['clients']['vms'],
                   fab.env['pu-pve2']['clients']['options'])
    scripts = _setup_ifaces(None, fab.env['pu-pve2']['clients']['vms'],
                            fab.env['pu-pve2']['settings']['vm'], False)
    # TODO: add scripts once we know what'd be running on these VMs.
    pve.vm_parallel_run(scripts)


@fab.roles('pu-pve2')
def pve2_cleanup_clients():
    pve.vm_destroy_multi(*_get_client_vm_id_list(fab.env['pu-pve2']['clients']['vms']))

