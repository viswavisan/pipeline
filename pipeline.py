import os
import time,datetime,requests
import subprocess
import git
import docker
from kubernetes import client, config
from jira import JIRA




class deployment_pipeline:
    def __init__(self, jira_id):
        self.jira_id = jira_id
        self.REPO_URL="https://github.com/viswavisan/fastapi_demo1.git"
        self.REPO_NAME='fastapi-demo'
        self.BRANCH='main'
        self.container_name=f'{self.REPO_NAME}-container'
        self.app_name=f'{self.REPO_NAME}'
        self.namespace = f'{self.REPO_NAME}-namespace'
        self.deployment_name=f'{self.REPO_NAME}-deployment' 
        self.service_name=f'{self.REPO_NAME}-service'
        self.image_name=f'{self.REPO_NAME}:latest'
        self.port=8000

    def run(self):

        self.build_latest_image()
        # self.kubernet_deployment()
        # self.check_service_status()
    



    def build_latest_image(self):
        print('building image...')
        if os.path.exists(self.REPO_NAME):
            repo = git.Repo(self.REPO_NAME)
            repo.git.checkout(self.BRANCH)
            repo.remotes.origin.pull()
        else:
            git.Repo.clone_from(self.REPO_URL,self.REPO_NAME, branch=self.BRANCH)

        d_client = docker.from_env()
        d_client.images.build(path='./'+self.REPO_NAME, tag=self.app_name)
        # push to ECR
        # d_client.images.push(self.image_name)
        
        #Run in docker
        try:
            existing_container = d_client.containers.get(self.container_name)
            if existing_container:existing_container.remove(force=True)
        except:pass

        for container in d_client.containers.list():
            if container.attrs['NetworkSettings']['Ports']:
                port_mapping = f"{self.port}/tcp"
                if port_mapping in container.attrs['NetworkSettings']['Ports']:
                    container.stop()
                    container.remove(force=True)

        d_client.containers.run(self.app_name, detach=True, name=self.container_name, ports={'8000/tcp': 8000})

    def kubernet_deployment(self):
        print('deployment start...')
        config.load_kube_config()
        core_v1 = client.CoreV1Api()  
    
        if self.namespace not in [ns.metadata.name for ns in core_v1.list_namespace().items]:
            print('creating namespace')
            namespace_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=self.namespace))
            core_v1.create_namespace(body=namespace_body)

        apps_v1 = client.AppsV1Api()
        if self.deployment_name in [deployment.metadata.name for deployment in apps_v1.list_namespaced_deployment(self.namespace).items]:
            print('updating deployment')
            deployment = apps_v1.read_namespaced_deployment(self.deployment_name, self.namespace)
            deployment.spec.template.spec.containers[0].image = self.image_name
            deployment = apps_v1.patch_namespaced_deployment( name=self.deployment_name, namespace=self.namespace, body=deployment )
        else:
            print('creating new deployment')
            container = client.V1Container(name=self.container_name,image=self.image_name,ports=[client.V1ContainerPort(container_port=self.port)],image_pull_policy='Never')
            pod_template = client.V1PodTemplateSpec(metadata=client.V1ObjectMeta(labels={"app":self.app_name}),spec=client.V1PodSpec(containers=[container]))
            deployment_spec = client.V1DeploymentSpec(replicas=1,template=pod_template,selector=client.V1LabelSelector(match_labels={"app":self.app_name}))
            deployment = client.V1Deployment(api_version="apps/v1",kind="Deployment",metadata=client.V1ObjectMeta(name=self.deployment_name),spec=deployment_spec)

        if self.service_name not in [service.metadata.name for service in core_v1.list_namespaced_service(self.namespace).items]:
            print('creating new service')
            apps_v1.create_namespaced_deployment(namespace=self.namespace, body=deployment)
            service = client.V1Service(api_version="v1",
                                    kind="Service",
                                    metadata=client.V1ObjectMeta(name=self.service_name),
                                    spec=client.V1ServiceSpec(selector={"app":self.app_name},
                                                                ports=[client.V1ServicePort(port=self.port, target_port=self.port)],
                                                                type="NodePort"))
            core_v1 = client.CoreV1Api()
            core_v1.create_namespaced_service(namespace=self.namespace, body=service)

    def check_service_status(self):
        try:
            pods = client.CoreV1Api().list_namespaced_pod(self.namespace, label_selector=f'app={self.app_name}')
            for pod in pods.items:
                if pod.status.phase != "Running":
                    print( {"status": "error", "message": f"Pod {pod.metadata.name} is not running."})

            service = client.CoreV1Api().read_namespaced_service(self.service_name, self.namespace)
            if service:
                node_ip = "localhost"
                response = requests.get(f'http://{node_ip}:{self.port}/main')
                if response.status_code == 200:
                    # jira.transition_issue(self.jira_id, '51')
                    print({"status": "success", "message": "Service is up and running."})
                else:print( {"status": "error", "message": f"Service returned status code: {response.status_code}"})
                
        except Exception as e:
            print( {"status": "error", "message": str(e)})


if __name__ == "__main__":
    deployment_pipeline('PPPDRP-6395').run()