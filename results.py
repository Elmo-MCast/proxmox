import re
import sample


def clean_results(log_file):
    results_log = open(log_file, 'r').read()

    results = []
    match = re.search(r'\<metric unit="ops/sec"\>(.+)\</metric\>', results_log, re.MULTILINE)

    if match:
        results.append(sample.Sample('Throughput', float(match.group(1)), 'ops/s'))

    matches = re.findall(r'\<avg\>(.+)\</avg\>', results_log, re.MULTILINE)
    if len(matches) > 0:
        sum_avg = 0.0
        for m in matches:
            sum_avg += float(m)
        avg_avg = 1000 * sum_avg / len(matches)
        results.append(sample.Sample('Average response time', avg_avg, 'ms'))

    return results
