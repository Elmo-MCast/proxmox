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


''' pu-pve2 Commands '''


@fab.roles('pu-pve2')
def pve2_configure_vswitch(execute=True):
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    ports = fab.env['pu-pve2']['bridge']['ports']
    proxmox_bridge = fab.env['vm']['proxmox']['bridge']
    script = pve_configure_vswitch(0x1, bridge_name, ports, False)
    script += "ip link add %s%si0 type veth peer name %s%si1; " \
              "ip link set dev %s%si0 up; ip link set dev %s%si1 up; " \
              "brctl addif %s %s%si0; " \
              % (bridge_name, proxmox_bridge, bridge_name, proxmox_bridge,
                 bridge_name, proxmox_bridge, bridge_name, proxmox_bridge,
                 proxmox_bridge, bridge_name, proxmox_bridge)
    script += ovs_add_port(bridge_name, "%s%si1" % (bridge_name, proxmox_bridge), False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


@fab.roles('pu-pve2')
def pve2_clear_vswitch(execute=True):
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    ports = fab.env['pu-pve2']['bridge']['ports']
    proxmox_bridge = fab.env['vm']['proxmox']['bridge']
    script = ovs_delete_port(bridge_name, "%s%si1" % (bridge_name, proxmox_bridge), False)
    script += "brctl delif %s %s%si0; " \
              "ip link del %s%si0; " \
              % (proxmox_bridge, bridge_name, proxmox_bridge,
                 bridge_name, proxmox_bridge)
    script += pve_clear_vswitch(bridge_name, ports, False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


@fab.roles('pu-pve2')
def pve2_configure_flow_rules(execute=True):
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    flow_rules = fab.env['pu-pve2']['bridge']['flow_rules']
    script = ""
    for flow_rule in flow_rules:
        script += ovs_add_flow(bridge_name, flow_rule, False)
    if is_execute(execute):
        fab.run(script)
    else:
        return script


@fab.roles('pu-pve2')
def pve2_clear_flow_rules(execute=True):
    bridge_name = fab.env['pu-pve2']['bridge']['name']
    return ovs_delete_flows(bridge_name, execute)