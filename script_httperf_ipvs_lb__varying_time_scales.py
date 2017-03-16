import json, os
import fabric.api as fab
import time

base_dirs = {
    'src': '/root/mshahbaz/notebooks/baseerat/runs/',
    'dst': '/root/mshahbaz/notebooks/baseerat/ipvs/results/timeseries/time-scales/'
}

X_max = {
    'rate': 64
}

num_clients = 8
run_time = 3
run_time_secs = run_time * 60
fluctuation_inerval = 500

run_params = 'single-backend/%sms-fluctuation/%smins-run' % (fluctuation_inerval, run_time)

web_servers = {
    '112': {
        'id': 0
    },
    '113': {
        'id': 1
    },
    '114': {
        'id': 2
    },
    '115': {
        'id': 3
    }
}

lb_servers = {
    '116': {
        'id': 0
    },
}

arrival_rates = {
    # '1_X_max': {
    #     'rate': (X_max['rate'] / num_clients),
    #     'num_conns': (X_max['rate'] / num_clients) * run_time_secs
    # },
    '2_X_max': {
        'rate': (2 * X_max['rate'] / num_clients),
        'num_conns': (2 * X_max['rate'] / num_clients) * run_time_secs
    },
    '3_X_max': {
        'rate': (3 * X_max['rate'] / num_clients),
        'num_conns': (3 * X_max['rate'] / num_clients) * run_time_secs
    }
}

seed_values = {
    # '112': [1, 2, 3],
    # '113': [11, 22, 33],
    # '114': [111, 222, 333],
    '115': [
        1111,
        2222,
        3333
    ],
}

feedback_intervals = {
    "1ms": 0.001,
    "5ms": 0.005,
    "20ms": 0.020,
    "200ms": 0.200,
    "600ms": 0.600,
    "1000ms": 1.000,
    "5000ms": 5.000
}

algos = {
    'wlc': {
        'is_dummy': True
    },
    'feedback-wlc': {
        'is_dummy': False
    }
}

with open("./httperf_ipvs_lb/httperf_ipvs_lb.config.json") as json_file:
    settings = json.load(json_file)

settings['httperf_ipvs_lb']['servers']['httperf_client']['options']['datetime']['dump'] = True

for arrival_rate in arrival_rates:
    for seed in seed_values['115']:
        for algo in algos:
            for feedback_interval in feedback_intervals:
                settings['httperf_ipvs_lb']['servers']['httperf_client']['config']['rate'] = \
                    arrival_rates[arrival_rate]['rate']
                settings['httperf_ipvs_lb']['servers']['httperf_client']['config']['num_conns'] = \
                    arrival_rates[arrival_rate]['num_conns']

                settings['httperf_ipvs_lb']['servers']['web_server']['vms'] \
                    [web_servers['115']['id']]['load']['seed_value'] = seed

                settings['httperf_ipvs_lb']['feedback']['is_dummy'] = algos[algo]['is_dummy']

                for web_server in web_servers:
                    settings['httperf_ipvs_lb']['servers']['web_server']['vms'] \
                        [web_servers[web_server]['id']]['state_server']['timeout'] = \
                        feedback_intervals[feedback_interval]
                for lb_server in lb_servers:
                    settings['httperf_ipvs_lb']['servers']['lb_server']['vms'] \
                        [lb_servers[lb_server]['id']]['state_server']['timeout'] = \
                        feedback_intervals[feedback_interval]

                with open("./httperf_ipvs_lb/httperf_ipvs_lb.json", 'w') as json_file:
                    json.dump(settings, json_file)

                print (arrival_rate, seed, algo, feedback_interval)

                time.sleep(10)
                fab.local("fab -f fabfile_httperf_ipvs_lb.py run")

                time.sleep(5)
                fab.local("fab -f fabfile_httperf_ipvs_lb.py clear")

                with open("/tmp/datetime_str.tmp") as datetime_str_file:
                    src_dir = datetime_str_file.read()
                dst_dir = '%s/%s/%s-feedback/%s/%s-seed' \
                          % (arrival_rate, run_params, feedback_interval, algo, seed)
                fab.local("fab -f fabfile_httperf_ipvs_lb.py collect_run:%s,%s"
                          % (base_dirs['src'] + src_dir,
                             base_dirs['dst'] + dst_dir))
                fab.local("rm -f /tmp/datetime_str.tmp")

