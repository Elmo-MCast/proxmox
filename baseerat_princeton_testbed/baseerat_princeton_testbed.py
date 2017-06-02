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


""" Helper Functions """

""" 'baseerat_princeton_testbed' Commands """

''' Common OVS Commands '''


def start_ovs(cpu_mask=0x1):
    var_path = fab.env['ovs']['paths']['var']
    ovsdb_path = fab.env['ovs']['paths']['base'] + "/ovsdb"
    vswitchd_path = fab.env['ovs']['paths']['base'] + "/vswitchd"
    script = "%s/ovsdb-server --remote=punix:%s/db.sock " \
             "--remote=db:Open_vSwitch,Open_vSwitch,manager_options --pidfile --detach; " \
             % (ovsdb_path, var_path,)
    script += "%s/ovs-vswitchd --dpdk -c %s -n 4 -- unix:%s/db.sock" \
              " --pidfile --detach" % (vswitchd_path, cpu_mask, var_path)
    fab.run(script)


def stop_ovs():
    var_path = fab.env['ovs']['paths']['var']
    script = "kill `cat %s/ovsdb-server.pid`; " \
             "kill `cat %s/ovs-vswitchd.pid`" % (var_path, var_path)
    fab.run(script)


def add_port(bridge_name, port):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    if port.startswith('dpdk'):
        script = "%s/ovs-vsctl add-port %s %s -- set Interface %s type=dpdk" \
                  % (utilities_path, bridge_name, port, port)
        fab.run(script)
    elif port.startswith('tap'):
        proxmox_bridge = fab.env['vm']['proxmox']['bridge']
        script = "brctl delif %s %s; " \
                 "%s/ovs-vsctl add-port %s %s" \
                 % (proxmox_bridge, port,
                    utilities_path, bridge_name, port)
        fab.run(script)
    else:
        print('Invalid interface (%s)' % (port,))


def delete_port(bridge_name, port):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    if port.startswith('dpdk'):
        script = "%s/ovs-vsctl del-port %s %s; " \
                  % (utilities_path, bridge_name, port)
        fab.run(script)
    elif port.startswith('tap'):
        proxmox_bridge = fab.env['vm']['proxmox']['bridge']
        script = "%s/ovs-vsctl del-port %s %s; " \
                 "brctl addif %s %s" \
                 % (utilities_path, bridge_name, port,
                    proxmox_bridge, port)
        fab.run(script)
    else:
        print('Invalid interface (%s)' % (port,))


def add_bridge(name='br0', *ports):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-vsctl add-br %s -- set bridge %s datapath_type=netdev; " \
             "%s/ovs-vsctl set bridge %s protocols=OpenFlow15" \
             % (utilities_path, name, name,
                utilities_path, name)
    fab.run(script)
    for port in ports:
        add_port(name, port)


def delete_bridge(name='br0'):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-vsctl del-br %s" \
             % (utilities_path, name)
    fab.run(script)
    # TODO: add tap interfaces back to the proxmox bridge!


def show_bridge(option='ofctl', bridge_name='br0'):  # options are: ofctl, vsctl
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    if option == 'ofctl':
        script = "%s/ovs-ofctl --protocols=OpenFlow15 show %s" % (utilities_path, bridge_name)
        fab.run(script)
    elif option == 'vsctl':
        script = "%s/ovs-vsctl show" % (utilities_path)
        fab.run(script)
    else:
        print('Invalid option (%s)' % (option,))


def dump_flows(bridge_name='br0'):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 dump-flows %s" \
             % (utilities_path, bridge_name)
    fab.run(script)


def delete_flows(bridge_name='br0'):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 del-flows %s" \
             % (utilities_path, bridge_name)
    fab.run(script)


def add_flow(bridge_name, **flow_rule):
    utilities_path = fab.env['ovs']['paths']['base'] + "/utilities"
    script = "%s/ovs-ofctl --protocols=OpenFlow15 add-flow %s '%s'" \
             % (utilities_path, bridge_name, ", ".join(['%s=%s' %(k, v) for k, v in flow_rule.iteritems()]))
    fab.run(script)


''' Configuring pu-pve2 machine (i.e., ToR and Clients'''

