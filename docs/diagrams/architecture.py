"""Renders docs/diagrams/architecture.png.  python3 docs/diagrams/architecture.py"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import EC2, Lambda
from diagrams.aws.database import DynamodbTable
from diagrams.aws.general import MobileClient, Users
from diagrams.aws.management import SystemsManager
from diagrams.aws.ml import Bedrock
from diagrams.onprem.client import User
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture")

with Diagram("WhatsApp KB bot", filename=OUT, show=False, direction="LR",
             graph_attr={"pad": "0.5", "nodesep": "0.6", "ranksep": "1.1", "fontsize": "20", "dpi": "160", "splines": "spline"}):
    with Cluster("WhatsApp"):
        group = Users("Support group\n(allowlisted)")
        phone = MobileClient("Bot phone\n(dedicated number)")

    with Cluster("AWS account, one region"):
        with Cluster("Dedicated VPC, public subnet\nno inbound ports"):
            ec2 = EC2("Listener  (EC2 t3.small)\nBaileys linked device\nsystemd, auto-restart")
        brain = Lambda("Brain  (Lambda, Python)\nclassify -> confidence floor\nanswer | silent")
        bedrock = Bedrock("Amazon Bedrock\nHaiku 4.5 classify\nSonnet 4.6 vision")
        kb = DynamodbTable("KB entries\n(DynamoDB)")
        ssm = SystemsManager("SSM Session Manager\nQR page + logs, no SSH")

    editor = User("KB editor\nkb.json -> publish.py")
    operator = User("Operator\nscripts/qr.sh")

    group >> Edge(label="message / screenshot") >> phone
    phone >> Edge(label="linked-device session\n(WhatsApp Web protocol)") >> ec2
    ec2 >> Edge(label="lambda:Invoke {text, image}\n<- {outcome, reply}") >> brain
    brain >> Edge(label="Converse API") >> bedrock
    brain >> Edge(label="Scan, 60 s cache") >> kb
    editor >> kb
    operator >> Edge(label="port-forward 8080") >> ssm >> ec2
