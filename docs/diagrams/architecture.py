"""Renders docs/diagrams/architecture.png.  python3 docs/diagrams/architecture.py  (needs `dot` on PATH)"""
import os

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import EC2, Lambda
from diagrams.aws.database import DynamodbTable
from diagrams.aws.general import MobileClient, Users
from diagrams.aws.management import SystemsManager
from diagrams.aws.ml import Bedrock
from diagrams.onprem.client import User

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture")

with Diagram("WhatsApp KB bot", filename=OUT, show=False, direction="LR",
             # A diagram that goes in an article has to be WIDE: a near-square render is
             # unreadable at Medium's column width. Keep labels short for the same reason.
             graph_attr={"pad": "0.4", "nodesep": "0.35", "ranksep": "1.1", "fontsize": "20",
                         "dpi": "160", "splines": "spline", "concentrate": "true"}):
    with Cluster("WhatsApp"):
        group_a = Users("Group: team-a\n(allowlisted)")
        group_b = Users("Group: team-b\n(allowlisted)")
        dm = User("1:1 message\n(group members only,\nDM_ENABLED)")
        phone = MobileClient("Bot phone\n(dedicated number)")

    with Cluster("AWS account, one region"):
        with Cluster("Dedicated VPC, public subnet, no inbound ports"):
            ec2 = EC2("Listener (EC2 t3.small)\nBaileys linked device\nroster every 15 min\nsystemd, auto-restart")
        brain = Lambda("Brain (Lambda, Python)\ntenant by group jid\nscreen -> classify -> floor\nanswer | ask once | silent")
        bedrock = Bedrock("Amazon Bedrock\nHaiku 4.5 screen + classify\nSonnet 4.6 vision\nbounded timeouts")
        with Cluster("Per tenant"):
            kb_a = DynamodbTable("KB team-a\n<prefix>-kb-team-a")
            kb_b = DynamodbTable("KB team-b\n<prefix>-kb-team-b")
        convo = DynamodbTable("Conversation state\nrate limit, supporter window,\n1:1 choice (TTL)")
        ssm = SystemsManager("SSM Session Manager\nQR page + logs, no SSH")

    with Cluster("Workstation (optional, daily)"):
        curator = User("KB curator\nreads bot.log over SSM\nA: trigger fix · B: draft · C: digest")
    editor = User("KB editor\ntenants/<id>/kb.json\nkbcheck -> publish")
    operator = User("Operator\nscripts/qr.sh")

    group_a >> Edge(label="message / screenshot") >> phone
    group_b >> phone
    dm >> phone
    phone >> Edge(label="linked-device session\n(WhatsApp Web protocol)") >> ec2
    ec2 >> Edge(label="lambda:Invoke\n{text, image, who, quoted, explicit, dm}\n<- {outcome, reply}") >> brain
    brain >> Edge(label="Converse API\n(cached catalogue prefix)") >> bedrock
    brain >> Edge(label="Scan, 60 s cache") >> kb_a
    brain >> kb_b
    brain >> Edge(label="conditional writes") >> convo
    # The people are off the message path, so their edges must not drive the ranking: without
    # constraint=false graphviz stacks the whole picture vertically and it stops being readable
    # at an article's column width.
    editor >> Edge(constraint="false") >> kb_a
    editor >> Edge(constraint="false") >> kb_b
    curator >> Edge(label="bot.log (read)", style="dashed", constraint="false") >> ssm
    curator >> Edge(label="triggers / drafts", style="dashed", constraint="false") >> kb_a
    operator >> Edge(label="port-forward 8080", constraint="false") >> ssm
    ssm >> Edge(constraint="false") >> ec2
