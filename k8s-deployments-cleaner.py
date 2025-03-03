from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException
from datetime import datetime, timezone
from loguru import logger
import argparse
import requests
import os

parser = argparse.ArgumentParser()
parser.add_argument('--dry', action='store_true', help='When present, indicates that modifications should not be persisted. In logs: [DRY RUN]')
parser.add_argument('--local', action='store_true', help='When present, loads authentication and cluster information from kube-config file')
parser.add_argument('--days', type=int, default=7, help='Retention days for failed deployments (default: 7)')
args = parser.parse_args()

if 'pachca_webhook_url' in os.environ and os.environ['pachca_webhook_url']:
    WEBHOOK_URL = os.environ.get('pachca_webhook_url')
else:
    logger.error("Env variable \"pachca_webhook_url\" not set or empty")
    exit(1)

if args.local:
    try:
        config.load_kube_config()
    except ConfigException as e:
        logger.error("kube-config file not found. Err_msg: {}", e)
        exit(1)
else:
    try:
        config.load_incluster_config()
    except ConfigException as e:
        logger.error("It seems you are trying to run script locally, use --local. Err_msg: {}", e)
        exit(1)

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
batch_v1 = client.BatchV1Api()
today = datetime.now(timezone.utc)

deleted_deployments = []
deleted_jobs = []
deleted_cronjobs = []

retention_days = args.days

def get_namespaces():
    namespaces_names = []
    logger.info("Getting namespaces ...")
    namespaces = core_v1.list_namespace(label_selector='hnc.x-k8s.io/included-namespace=true', watch=False)
    for ns in namespaces.items:
        namespaces_names.append(ns.metadata.name)
    return namespaces_names

def get_failed_pods():
    namespaces_names = get_namespaces()
    failed_pod_of_deployments = []
    failed_pod_of_jobs = []
    logger.info("Looking for failed Pods ...")
    for ns in namespaces_names:
        pods = core_v1.list_namespaced_pod(namespace=ns, watch=False)
        for pod in pods.items:
            if pod.metadata.owner_references:
                if pod.metadata.owner_references[0].kind == 'ReplicaSet':
                    if pod.status.container_statuses:
                        for condition in pod.status.container_statuses:
                            if ((not condition.state.running) or (condition.state.terminated and condition.state.terminated.reason != "Completed")):
                                failed_pod_of_deployments.append(pod)
                if pod.metadata.owner_references[0].kind == 'Job':
                    if pod.status.container_statuses:
                        for condition in pod.status.container_statuses:
                            if ((not condition.state.running) and (condition.state.terminated and condition.state.terminated.reason != "Completed")) or ((not condition.state.running) and (condition.state.waiting and condition.state.waiting.reason == "ImagePullBackOff")):
                                failed_pod_of_jobs.append(pod)
    get_failed_deployments(failed_pod_of_deployments)
    get_failed_jobs(failed_pod_of_jobs)
    

def get_failed_deployments(failed_pod_of_deployments):
    failed_deployments = []
    logger.info("Looking for failed Deployments ...")
    for pod in failed_pod_of_deployments:
        creation_timestamp = pod.metadata.creation_timestamp
        creation_time = creation_timestamp.replace(tzinfo=timezone.utc)
        time_diff = today - creation_time
        days_passed = time_diff.days
        if days_passed > retention_days:
            replicaset_name = pod.metadata.owner_references[0].name
            replicaset_name_splitted = replicaset_name.rsplit("-", 1)[0]
            try:
                dep_info = apps_v1.read_namespaced_deployment(name=replicaset_name_splitted, namespace=pod.metadata.namespace)
            except ApiException as e:
                logger.warning("Exception when calling AppsV1Api->get_namespaced_deployment: {}", e)
            if (dep_info.status.replicas != 0) and (dep_info.status.replicas == dep_info.status.unavailable_replicas):
                if replicaset_name_splitted not in failed_deployments:
                    collection = {}
                    collection['name'] = replicaset_name_splitted
                    collection['ns'] = pod.metadata.namespace
                    failed_deployments.append(collection)
    delete_deployments(failed_deployments)


def get_failed_jobs(failed_pod_of_jobs):
    logger.info("Looking for failed Jobs ...")
    failed_jobs = []
    failed_cronjobs = []
    for pod in failed_pod_of_jobs:
        collection = {}
        collection['name'] = pod.metadata.owner_references[0].name
        collection['ns'] = pod.metadata.namespace
        failed_jobs.append(collection)
    seen = set()
    # remove duplicates
    unique_failed_jobs = [x for x in failed_jobs if tuple(x.items()) not in seen and not seen.add(tuple(x.items()))]
    
    for job in unique_failed_jobs:
        try:
            job_info = batch_v1.read_namespaced_job(name=job['name'], namespace=job['ns'])
        except ApiException as e:
            logger.warning("Exception when calling BatchV1Api->read_namespaced_job: {}", e)
        if job_info.metadata.owner_references:
            collection = {}
            collection['name'] = job_info.metadata.owner_references[0].name
            collection['ns'] = job_info.metadata.namespace
            failed_cronjobs.append(collection)
    delete_cronjobs(failed_cronjobs)
    delete_jobs(unique_failed_jobs)

def delete_jobs(unique_failed_jobs):
    if len(unique_failed_jobs) == 0:
        logger.info("No failed jobs found")
        return
    dry_run = None
    dry_run_msg = ""
    if args.dry:
        dry_run = "All"
        dry_run_msg = "[DRY RUN]"
    for job in unique_failed_jobs:
        logger.info("Failed job found: {}, in ns: {}", job['name'], job['ns'])
        logger.warning("{} Deleting job {} from ns {}", dry_run_msg, job['name'], job['ns'])
        try:
            batch_v1.delete_namespaced_job(name=job['name'], namespace=job['ns'], dry_run=dry_run)
            deleted_jobs.append(job)
        except ApiException as e:
            logger.error("Exception when calling BatchV1Api->delete_namespaced_job: {}", e)

def delete_cronjobs(failed_cronjobs):
    if len(failed_cronjobs) == 0:
        logger.info("No failed cron jobs found")
        return

    dry_run = None
    dry_run_msg = ""
    if args.dry:
        dry_run = "All"
        dry_run_msg = "[DRY RUN]"
    for cronjob in failed_cronjobs:
        logger.info("Failed cronjob found: {}, in ns: {}", cronjob['name'], cronjob['ns'])
        logger.warning("{} Deleting cronjob {} from ns {}", dry_run_msg, cronjob['name'], cronjob['ns'])
        try:
            batch_v1.delete_namespaced_cron_job(name=cronjob['name'], namespace=cronjob['ns'], dry_run=dry_run)
            deleted_cronjobs.append(cronjob)
        except ApiException as e:
            logger.error("Exception when calling BatchV1Api->delete_namespaced_cron_job: {}", e)

def delete_deployments(failed_deployments):
    if len(failed_deployments) == 0:
        logger.info("No failed deployments found")
        return
    dry_run = None
    dry_run_msg = ""
    if args.dry:
        dry_run = "All"
        dry_run_msg = "[DRY RUN]"
    for deployment in failed_deployments:
        logger.info("Failed deployment found: {}, in ns: {}", deployment['name'], deployment['ns'])
        logger.warning("{} Deleting deployment {} from ns {}", dry_run_msg, deployment['name'], deployment['ns'])
        try:
            apps_v1.delete_namespaced_deployment(name=deployment['name'], namespace=deployment['ns'], dry_run=dry_run)
            collection = {}
            collection['ns'] = deployment['ns']
            collection['name'] = deployment['name']
            deleted_deployments.append(deployment)
        except ApiException as e:
            logger.error("Exception when calling AppsV1Api->delete_namespaced_deployment: {}", e)
    logger.info("{} Total deleted deployments: {}", dry_run_msg, len(deleted_deployments))

def notify(deleted_deployments, deleted_cronjobs, deleted_jobs):
    if all(not lst for lst in [deleted_deployments, deleted_cronjobs, deleted_jobs]):
      logger.info("Nothing to notify")
      return
    dry_run_msg = ""
    if args.dry:
        dry_run_msg = "[DRY RUN]"
    payload = {
        "days": retention_days,
        "dry": dry_run_msg
        }
    print(deleted_deployments)
    if deleted_deployments:
        payload['deployments'] = deleted_deployments
    if deleted_jobs:
        payload['jobs'] = deleted_jobs
    if deleted_cronjobs:
        payload['cronjobs'] = deleted_cronjobs

    webhook_response = requests.post(WEBHOOK_URL, json=payload, headers={'Content-Type': 'application/json'})
    webhook_response.raise_for_status()
    logger.info("Webhook sent successfully")

if __name__ == "__main__":
    get_failed_pods()
    notify(deleted_deployments=deleted_deployments, deleted_cronjobs=deleted_cronjobs, deleted_jobs=deleted_jobs)
