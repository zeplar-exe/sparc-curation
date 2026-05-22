import matplotlib.pyplot as plt
import json
from collections import Counter, defaultdict
import csv
import datetime
import matplotlib.dates as mdates
import numpy as np


TEMPORAL_REPORT = "./temporal_report.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
SPARCUR_UPDATES = "./sparcur_updates.csv"


def parse_iso8601(date_str):
    if not date_str:
        return None
    return datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))

def parse_mmddyyyy(date_str):
    return datetime.datetime.strptime(date_str, '%m-%d-%Y')

with open(TEMPORAL_REPORT) as f, open(EVENT_SEQUENCES) as g, open(SPARCUR_UPDATES) as h:
    temporal_report = json.load(f)
    event_sequences = json.load(g)
    sparcur_updates = list(csv.DictReader(h))

    # Standards Adherence: errors at first request over time
    error_diff_records = []

    for dataset_id, dataset_record in temporal_report.items():
        events = event_sequences.get(dataset_id)
        if not events or not isinstance(events, list):
            continue

        error_graph = dataset_record.get('error_graph', {})
        org = (
            'precision' if dataset_record.get('is_precision') else
            'sparc' if dataset_record.get('is_sparc') else
            'rejoin' if dataset_record.get('is_rejoin') else
            'unknown'
        )
        uses_soda = dataset_record.get('uses_soda', False)

        for event in events:
            if event.get("incomplete"):
                continue
            req_created = event.get("request_created")
            pub_created = event.get("accept_created")
            if not req_created or not pub_created:
                continue
            req_time = parse_iso8601(req_created)
            pub_time = parse_iso8601(pub_created)
            if not req_time or not pub_time:
                continue
            req_ts = int(req_time.timestamp())
            pub_ts = int(pub_time.timestamp())

            # Find first error_graph entry after request
            req_error_time = None
            req_error_count = None
            for ts_str, errors in error_graph.items():
                ts_int = int(ts_str)
                if ts_int >= req_ts and (req_error_time is None or ts_int < req_error_time):
                    req_error_count = sum(errors.values())
                    req_error_time = ts_int

            # Find first error_graph entry after publication
            pub_error_time = None
            pub_error_count = None
            for ts_str, errors in error_graph.items():
                ts_int = int(ts_str)
                if ts_int >= pub_ts and (pub_error_time is None or ts_int < pub_error_time):
                    pub_error_count = sum(errors.values())
                    pub_error_time = ts_int

            if req_error_count is None or pub_error_count is None:
                continue

            error_diff = pub_error_count - req_error_count
            error_diff_records.append({
                'dataset_id': dataset_id,
                'request_time': req_time,
                'error_diff': error_diff,
                'uses_soda': uses_soda,
                'org': org
            })

    colors = {
        'precision': 'tab:blue',
        'sparc': 'tab:orange',
        'rejoin': 'tab:green',
        'unknown': 'tab:gray'
    }

    org_list = ['precision', 'sparc', 'rejoin']
    soda_options = [(True, 'SODA'), (False, 'non-SODA')]

    for soda_val, soda_label in soda_options:
        for org in org_list:
            x_vals = [r['request_time'] for r in error_diff_records if r['uses_soda'] == soda_val and r['org'] == org]
            y_vals = [r['error_diff'] for r in error_diff_records if r['uses_soda'] == soda_val and r['org'] == org]

            if not x_vals:
                continue

            fig, ax = plt.subplots(figsize=(10, 6))
            color = colors.get(org, 'tab:gray')
            ax.scatter(x_vals, y_vals, label=f'{soda_label} {org}', marker='o', color=color, alpha=0.7)

            min_x = min(x_vals)
            y0, y1 = ax.get_ylim()
            n_updates = sum(
                1 for update in sparcur_updates if parse_mmddyyyy(update['date']) and (
                    (min_x.tzinfo is not None and parse_mmddyyyy(update['date']).replace(tzinfo=min_x.tzinfo) >= min_x) or
                    (min_x.tzinfo is None and parse_mmddyyyy(update['date']) >= min_x)
                )
            )
            label_idx = 0
            for update in sparcur_updates:
                update_date = parse_mmddyyyy(update['date'])
                if update_date:
                    if min_x.tzinfo is not None and update_date.tzinfo is None:
                        update_date = update_date.replace(tzinfo=min_x.tzinfo)
                    elif min_x.tzinfo is None and update_date.tzinfo is not None:
                        min_x = min_x.replace(tzinfo=update_date.tzinfo)
                    if update_date >= min_x:
                        ax.axvline(update_date, color='tab:red', linestyle='--', alpha=0.7)
                        y_frac = 0.95 - 0.15 * (label_idx % max(n_updates, 1))
                        y_pos = y0 + (y1 - y0) * y_frac
                        ax.text(update_date, y_pos, update['version'], rotation=90, color='tab:red', va='top', ha='right', fontsize=8)
                        label_idx += 1

            ax.set_xlabel('First Request Date')
            ax.set_ylabel('Error Count Difference (Publication - Request)')
            ax.set_title(f'Standards Adherence: Error Difference (Publication - Request)\n{soda_label} {org}')

            y_absmax = max(abs(min(y_vals)), abs(max(y_vals)))
            y_buffer = max(1, y_absmax * 0.05)
            ax.set_ylim(-y_absmax - y_buffer, y_absmax + y_buffer)
            ax.axhline(0, color='gray', linestyle='--', alpha=0.5, zorder=0)
            ax.legend()
            fig.autofmt_xdate()
            plt.tight_layout()
            plt.show()

    # Time from first request to publication (box plot per year)
    durations_by_year = defaultdict(list)
    
    for dsid, events in event_sequences.items():
        if not isinstance(events, list) or not events:
            continue
        ev = events[0]
        req = parse_iso8601(ev.get('request_created'))
        pub = parse_iso8601(ev.get('accept_created'))
        if req and pub and pub > req:
            year = req.year
            duration = (pub - req).days
            durations_by_year[year].append(duration)
    
    if durations_by_year:
        years = sorted(durations_by_year.keys())
        data = [durations_by_year[y] for y in years]
        fig, ax = plt.subplots(figsize=(10,6))
        
        ax.boxplot(data, vert=False, labels=years)
        ax.set_ylabel('Request Year')
        ax.set_xlabel('Days from Request to Publication')
        ax.set_title('Time from First Request to Publication by Year')
        plt.tight_layout()
        plt.show()