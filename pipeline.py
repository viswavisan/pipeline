import os
import time,datetime,requests
import subprocess
import git
import docker
from kubernetes import client, config

class deployment_pipeline:
    def __init__(self):
        
        self.build='ECR'
        if self.build=='local':self.container_path=''
        else:self.container_path="ghcr.io/viswavisan/"
        self.deployment_type='kubernets'

        self.REPO_NAME='fastapi-demo1'
        self.REPO_URL=f"https://github.com/viswavisan/{self.REPO_NAME}.git"
        self.BRANCH='main'

        self.expose_port=8000
        self.port=8000

        self.image_name=f'{self.container_path}{self.REPO_NAME}:latest' 
        print(self.image_name)
        self.container_name=f'{self.REPO_NAME}-container'
        self.app_name=f'{self.REPO_NAME}'
        self.namespace = f'{self.REPO_NAME}-namespace'
        self.deployment_name=f'{self.REPO_NAME}-deployment' 
        self.service_name=f'{self.REPO_NAME}-service'
    
        self.d_client = docker.from_env()

    def run(self):
        self.pull_latest_code()
        self.build_latest_image()
        if self.deployment_type=='docker':self.deploy_in_docker()
        elif self.deployment_type=='kubernets':
            self.kubernet_deployment()
            self.check_service_status()
        self.check_application_status()
    
    def pull_latest_code(self):
        print('pulling latest code from repository')
        if os.path.exists(self.REPO_NAME):
            repo = git.Repo(self.REPO_NAME)
            repo.git.checkout(self.BRANCH)
            repo.remotes.origin.pull()
        else:
            git.Repo.clone_from(self.REPO_URL,self.REPO_NAME, branch=self.BRANCH)

    def build_latest_image(self):
        print('building image...')
        try:
            # self.d_client.images.build(path='./'+self.REPO_NAME, tag=self.image_name)
            image, build_logs = self.d_client.images.build(path='./' + self.REPO_NAME, tag=self.image_name)
            for log in build_logs:print(log)
            print(image)
        except Exception as e: print(str(e))

        if self.build!='local':
            # self.d_client.login(username='viswavisan', password='1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', registry='ghcr.io') 
            os.system('echo 1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 | docker login ghcr.io -u viswavisan --password-stdin')
            push_response = self.d_client.images.push(self.image_name, stream=True, decode=True)
            for line in push_response:print(line) 
        
    def deploy_in_docker(self):
        print('deployment started in docker')

        try:
            existing_container = self.d_client.containers.get(self.container_name)
            if existing_container:existing_container.remove(force=True)
        
            for container in self.d_client.containers.list():
                if container.attrs['NetworkSettings']['Ports']:
                    port_mapping = f"{self.port}/tcp"
                    if port_mapping in container.attrs['NetworkSettings']['Ports']:
                        container.stop()
                        container.remove(force=True)
        except:pass

        self.d_client.containers.run(self.image_name, detach=True, name=self.container_name, ports={f'{self.port}/tcp': self.expose_port})

    def kubernet_deployment(self):
        try:
            print('deployment start...')

            config.load_kube_config()
            core_v1 = client.CoreV1Api()  
            print([ns.metadata.name for ns in core_v1.list_namespace().items])
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
                container = client.V1Container(name=self.container_name,image=self.image_name,ports=[client.V1ContainerPort(container_port=self.port)],image_pull_policy='Always')
                pod_template = client.V1PodTemplateSpec(metadata=client.V1ObjectMeta(labels={"app":self.app_name}),spec=client.V1PodSpec(containers=[container]))
                deployment_spec = client.V1DeploymentSpec(replicas=1,template=pod_template,selector=client.V1LabelSelector(match_labels={"app":self.app_name}))
                deployment = client.V1Deployment(api_version="apps/v1",kind="Deployment",metadata=client.V1ObjectMeta(name=self.deployment_name),spec=deployment_spec)
                # print(deployment)
            if self.service_name not in [service.metadata.name for service in core_v1.list_namespaced_service(self.namespace).items]:
                print('creating new service')
                apps_v1.create_namespaced_deployment(namespace=self.namespace, body=deployment)
                service = client.V1Service(api_version="v1",
                                        kind="Service",
                                        metadata=client.V1ObjectMeta(name=self.service_name),
                                        spec=client.V1ServiceSpec(selector={"app":self.app_name},
                                                                    ports=[client.V1ServicePort(port=self.port, target_port=self.expose_port)],
                                                                    type="NodePort"))
                core_v1 = client.CoreV1Api()
                core_v1.create_namespaced_service(namespace=self.namespace, body=service)
        except Exception as e:print(str(e))
    def check_service_status(self):
        pods = client.CoreV1Api().list_namespaced_pod(self.namespace, label_selector=f'app={self.app_name}')
        for pod in pods.items:
            if pod.status.phase != "Running":print( {"status": "error", "message": f"Pod {pod.metadata.name} is not running."})
        service = client.CoreV1Api().read_namespaced_service(self.service_name, self.namespace)
        if not service:print( {"status": "error", "message": "Service not running"})

    def check_application_status(self):
        time.sleep(3)
        print('checking application status')
        node_ip = "localhost"
        response = requests.get(f'http://{node_ip}:{self.expose_port}/main')
        if response.status_code == 200:print({"status": "success", "message": "Service is up and running."})
        else:print( {"status": "error", "message": f"Service returned status code: {response.status_code}"})
                
if __name__ == "__main__":
    deployment_pipeline().run()
