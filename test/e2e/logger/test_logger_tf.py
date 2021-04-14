# Copyright 2020 kubeflow.org.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from kubernetes import client
import numpy as np
from kfserving import KFServingClient
from kfserving import constants
from kfserving import V1alpha2EndpointSpec
from kfserving import V1alpha2PredictorSpec
from kfserving import V1alpha2CustomSpec
from kfserving import V1alpha2TensorflowSpec
from kfserving import V1alpha2InferenceServiceSpec
from kfserving import V1alpha2InferenceService
from kfserving import V1alpha2Logger
from kubernetes.client import V1ResourceRequirements
from kubernetes.client import V1Container
from ..common.utils import predict
from ..common.utils import KFSERVING_TEST_NAMESPACE
import time

api_version = constants.KFSERVING_GROUP + '/' + constants.KFSERVING_VERSION
KFServing = KFServingClient(config_file=os.environ.get("KUBECONFIG", "~/.kube/config"))


def test_kfserving_logger():
    msg_dumper = 'message-dumper'
    default_endpoint_spec = V1alpha2EndpointSpec(
        predictor=V1alpha2PredictorSpec(
            min_replicas=1,
            custom=V1alpha2CustomSpec(
                container=V1Container(
                    name="kfserving-container",
                    image='gcr.io/knative-releases/knative.dev/eventing-contrib/cmd/event_display',
                ))))

    isvc = V1alpha2InferenceService(api_version=api_version,
                                    kind=constants.KFSERVING_KIND,
                                    metadata=client.V1ObjectMeta(
                                        name=msg_dumper, namespace=KFSERVING_TEST_NAMESPACE),
                                    spec=V1alpha2InferenceServiceSpec(default=default_endpoint_spec))

    KFServing.create(isvc)
    KFServing.wait_isvc_ready(msg_dumper, namespace=KFSERVING_TEST_NAMESPACE)

    service_name = 'isvc-tensorflow'
    default_endpoint_spec = V1alpha2EndpointSpec(
        predictor=V1alpha2PredictorSpec(
            min_replicas=1,
            logger=V1alpha2Logger(
               mode="all",
               url="http://message-dumper."+KFSERVING_TEST_NAMESPACE+".svc.cluster.local"
            ),
            tensorflow=V1alpha2TensorflowSpec(
                storage_uri='gs://kfserving-samples/models/tensorflow/flowers',
                resources=V1ResourceRequirements(
                    requests={'cpu': '1', 'memory': '2Gi'},
                    limits={'cpu': '1', 'memory': '2Gi'}))))

    isvc = V1alpha2InferenceService(api_version=api_version,
                                    kind=constants.KFSERVING_KIND,
                                    metadata=client.V1ObjectMeta(
                                        name=service_name, namespace=KFSERVING_TEST_NAMESPACE),
                                    spec=V1alpha2InferenceServiceSpec(default=default_endpoint_spec))

    KFServing.create(isvc)
    try:
        KFServing.wait_isvc_ready(service_name, namespace=KFSERVING_TEST_NAMESPACE)
    except RuntimeError:
        pods = KFServing.core_api.list_namespaced_pod(KFSERVING_TEST_NAMESPACE,
                                                      label_selector='serving.kubeflow.org/inferenceservice={}'.
                                                      format(service_name))
        for pod in pods.items:
            print(pod)

    res = predict(service_name, './data/flower_input.json')
    assert(np.argmax(res["predictions"][0].get('scores')) == 0)
    pods = KFServing.core_api.list_namespaced_pod(KFSERVING_TEST_NAMESPACE,
                                                  label_selector='serving.kubeflow.org/inferenceservice={}'.
                                                  format(msg_dumper))
    time.sleep(5)
    log = ''
    for pod in pods.items:
        log += KFServing.core_api.read_namespaced_pod_log(name=pod.metadata.name,
                                                          namespace=pod.metadata.namespace,
                                                          container="kfserving-container")
        print(log)
    assert("org.kubeflow.serving.inference.request" in log)
    assert("org.kubeflow.serving.inference.response" in log)

    predict(service_name, './data/flower_input_invalid.json')
    log = ''
    for pod in pods.items:
        log += KFServing.core_api.read_namespaced_pod_log(name=pod.metadata.name,
                                                          namespace=pod.metadata.namespace,
                                                          container="kfserving-container")
        print(log)
    assert("Missing" in log)

    KFServing.delete(service_name, KFSERVING_TEST_NAMESPACE)
    KFServing.delete(msg_dumper, KFSERVING_TEST_NAMESPACE)
