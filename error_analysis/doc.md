# Error Analysis Codebase Documentation

## General Curation Export Error Matching/Classification

Relevant Code Files:
- test_format.py
    Depends on:
        error-info.json
    Generates:
        format-regexes.txt
        format-matches.csv
- error_info_to_json.py
    Depends on:
        error-info.txt
- group_path_errors.py
    Generates:
        jsonschema_errors.txt

Relevant Resource/Generated Files (assumes unchanged configuration):
- error-info.txt
    Created by test_format.py
    Contains hard-coded error classifications, their descriptions, and an associated RegEx for matching from error logs
- error-info.json
    Created by error_info_to_json.py
    Contains a JSON-structured representation of error-info.txt
- format-regexes.txt
    Created by test_format.py
    Contains the regexes used for matching each error type
- format-matches.csv
    Created by test_format.py
    Contains the frequency of each error type on the target file
- jsonschema_errors.txt
    Created by group_path_errors.py
    Contains groupings of unique errors and the frequencies of associated paths


NOTE: All downstream error-based operations (such as TemporalReporter) depend on test_format.py, and thus depend on error-info.json/error-info.txt


## Cassava Dataset Syncing

Relevant Code Files:
- unzip_cassava.py
    Generates:
        missings.json (if enabled)
        cassava_crawl_{date}.json (if enabled)
        \[dataset_tarxz_url\].json in OUT folder for every curation export in Cassava
- read_snapshot.py
    Legacy file
- cassava_crawler.js
    TamperMonkey script
    Generates cassava_crawl_{date}.json (printed to the JavaScript console)

Relevant Resource/Generated Files (assumes unchanged configuration):
- missings.json
    Created by unzip_cassava.py
    Contains a JSON list of crawled curation exports that do not have local copies
- cassava_crawl_{date}.json
    Created by cassava_crawler.js


## Cassava Dataset Analysis

Relevant Code Files:
- temporal_report.py
    Depends on:
        Exports from unzip_cassava.py
        protocol_target_ids.csv (if UrlIdentifierReporter enabled)
        identifiers_for_soda_processed_datasets_marked_as_published.csv (if TemporalReporter enabled)
    Generates:
        temporal_report.json (if TemporalReporter enabled)
        dropped_errors.txt (if TemporalReporter enabled)
        path_errors.txt (if PathErrorReporter enabled)
        dataset_relations.csv (if UrlIdentifierReporter enabled)
        principal_investigator_frequency.json (if PrincipalInvestigatorReporter enabled)
- temporal_report_to_list.py
    Generates:
        temporal_report_list.json

Relevant Resource/Generated Files (assumes unchanged configuration):
- temporal_report.json
    Created by temporal_report.py (TemporalReporter module)
    Contains error data across all curation exports for every dataset scraped via unzip_cassava.py
- dropped_errors.txt
    Created by the (TemporalReporter module)
    Contains errors that did not match any classified error RegEx while reporting
- path_errors.txt
    Created by temporal_report.py (PathErrorReporter module)
    Contains every available path error from the every curation export of each dataset scraped via unzip_cassava.py
    Intended for validating test_formaats.py
- dataset_relations.csv
    Created by temporal_report.py (UrlIdentifierReporter module)
- principal_investigator_frequency.json
    Created by temporal_report.py (PrincipalInvestigatorReporter module)
- temporal_report_list.json
    Created by temporal_report_to_list.py
    Useful for import into data visualizers like Tableau
- protocol_target_ids.csv
    Used by temporal_report.py (UrlIdentifierReporter module)
- identifiers_for_soda_processed_datasets_marked_as_published.csv
    Used by temporal_report.py (TemporalReporter module)

## Pennsieve Event Data Analysis

Relevant Code Files:
- read_pennsieve_series.py
    Depends on:
        pennsieve-event-data-2026-05-12T020310Z.json
    Generates:
        pennsieve_event_series.json
- read_pennsieve_stati.py
    Depends on:
        pennsieve_event_series.json
    Generates:
        pennsieve_status_delimited.json 
- pennsieve_status_cluster.py
    Depends on:
        pennsieve_status_delimited.json 
    Generates:
        pennsieve_curation_clusters.json

Relevant Resource/Generated Files (assumes unchanged configuration):
- pennsieve_event_series.json
    Created by read_pennsieve_series.py
    Contains every dataset and its chronological sequences of events from REQUEST_PUBLICATION/EMBARGO to ACCEPT_PUBLICATION/EMBARGO
- pennsieve_status_delimited.json
    Created by read_pennsieve_stati.py
    Contains every dataset and sequences of curation events delimited by UPDATE_STATUS events to curation stati
- pennsieve_curation_clusters.json
    Created by pennsieve_staus_cluster.py
    Contains every dataset and extrapolated estimates of continuous curation sessions


## Data Visualization

Relevant Code Files:
- curation_report.py
    Outputs 6 metric visualizations:
        Standards adherence: error diff over time (SODA vs non-SODA | SPARC, PRECISION, REJOIN)
        Time from first request to publication (box plot per year)
        Event type totals per year (stacked bar chart)
        Total curation events per dataset by first request year
        Datasets by first request date vs summed curations
        Datasets by first request date vs average cluster length
    Depends on:
        temporal_report.json
        pennsieve_event_series.json
        pennsueve_curation_clusters.json
        pennsieve_status_delimited.json
        sparcur_updates.csv

Relevant Resource/Generated Files (assumes unchanged configuration):
- sparcur_updates.csv
    Used by curation_report.py
    Contains names and dates of sparcur releases


# Pipeline Instructions

## Testing error-info.txt on a File of Errors


## Scraping Cassava


## Producing a Report of Errors over Time


### Extra: Importing into Tableau


## Generating a Curation Report


## Analyzing Curation Events (pennsieve) and Clusters
