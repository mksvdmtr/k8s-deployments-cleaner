from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException
from datetime import datetime, timezone
from loguru import logger
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--dry', action='store_true', help='When present, indicates that modifications should not be persisted. In logs: [DRY RUN]')
parser.add_argument('--local', action='store_true', help='When present, loads authentication and cluster information from kube-config file')
args = parser.parse_args()

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
today = datetime.now(timezone.utc)
namespaces_names = []
failed_deployments = []
retention_days = 3

def get_namespaces():
    logger.info("Getting namespaces ...")
    namespaces = core_v1.list_namespace(label_selector='hnc.x-k8s.io/included-namespace=true', watch=False)
    for ns in namespaces.items:
        namespaces_names.append(ns.metadata.name)

def get_failed_deployments():
    logger.info("Looking for failed deployments ...")
    for ns in namespaces_names:
        pods = core_v1.list_namespaced_pod(namespace=ns, watch=False)
        for pod in pods.items:
            if pod.metadata.owner_references:
                if pod.metadata.owner_references[0].kind == 'ReplicaSet':
                    for condition in pod.status.container_statuses:
                        if ((not condition.state.running) or (condition.state.terminated and condition.state.terminated.reason != "Completed")):
                            creation_timestamp = pod.metadata.creation_timestamp
                            creation_time = creation_timestamp.replace(tzinfo=timezone.utc)
                            time_diff = today - creation_time
                            days_passed = time_diff.days
                            if days_passed > retention_days:
                                replicaset_name = pod.metadata.owner_references[0].name
                                replicaset_name_splitted = replicaset_name.rsplit("-", 1)[0]
                                dep_info = apps_v1.read_namespaced_deployment(name=replicaset_name_splitted, namespace=pod.metadata.namespace)
                                if (dep_info.status.replicas != 0) and (dep_info.status.replicas == dep_info.status.unavailable_replicas):
                                    if replicaset_name_splitted not in failed_deployments:
                                        collection = {}
                                        collection['name'] = replicaset_name_splitted
                                        collection['ns'] = pod.metadata.namespace
                                        collection['pod_creation_timestamp'] = pod.metadata.creation_timestamp
                                        failed_deployments.append(collection)

def delete_deployments():
    if len(failed_deployments) == 0:
        logger.info("No failed deployments found")
        exit(0)
    dry_run = None
    dry_run_msg = ""
    if args.dry:
        dry_run = "All"
        dry_run_msg = "[DRY RUN]"
    for deployment in failed_deployments:
        logger.info("Failed deployment found: {}, one of its pods was created: {} in ns: {}", deployment['name'], deployment['pod_creation_timestamp'], deployment['ns'])
        logger.warning("{} Deleting deployment {} from ns {}", dry_run_msg, deployment['name'], deployment['ns'])
        try:
            apps_v1.delete_namespaced_deployment(name=deployment['name'], namespace=deployment['ns'], dry_run=dry_run)
        except ApiException as e:
            logger.error("Exception when calling AppsV1Api->delete_namespaced_deployment: {}", e)

if __name__ == "__main__":
    get_namespaces()
    get_failed_deployments()
    delete_deployments()
