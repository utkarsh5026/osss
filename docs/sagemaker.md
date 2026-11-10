# Using osss on SageMaker

osss was designed with SageMaker in mind. It works in **SageMaker Studio** (JupyterLab and Code Editor) and on **classic notebook instances**, with no extra AWS setup beyond what your notebook already has.

## Quick start

```python
%pip install -q "osss @ git+https://github.com/utkarsh5026/osss.git"

import osss
cluster = osss.start()
idx = cluster.create_index("docs", "s3://your-bucket/your-prefix/")
idx.search("your question")
```

Or open the app with `osss.ui()` and click through it.

## Studio vs. notebook instances

=== "SageMaker Studio"

    - **No Docker** in Studio, so osss uses the self-contained tarball (bundled Java, about 250 MB, downloaded once per space).
    - Data lives in `~/.osss`, which is on the space's persistent storage, so your indexes survive stopping and restarting the space.
    - If your kernel runs as **root** (Studio Classic, some custom images), OpenSearch refuses to run as root. osss then starts it as the unprivileged `nobody` user and keeps data in `/opt/osss`. To keep that data on persistent storage, choose a location before starting:

    ```python
    import os
    os.environ["OSSS_HOME"] = "/home/sagemaker-user/osss-data"
    import osss
    cluster = osss.start()
    ```

=== "Notebook instances"

    - Docker is available, so osss runs the official OpenSearch container with a persistent volume.
    - To preinstall osss whenever the instance starts, add this to a **lifecycle configuration** (*On start*):

    ```bash
    #!/bin/bash
    set -e
    sudo -u ec2-user -i <<'EOF'
    source /home/ec2-user/anaconda3/bin/activate python3
    pip install -q "osss @ git+https://github.com/utkarsh5026/osss.git"
    source /home/ec2-user/anaconda3/bin/deactivate
    EOF
    ```

## Permissions

osss uses the notebook's **execution role**. No access keys are needed.

| To… | The role needs |
| --- | --- |
| Index from S3 | `s3:ListBucket` on the bucket, `s3:GetObject` on the objects |
| Use Bedrock embeddings | `bedrock:InvokeModel`, plus model access enabled in the Bedrock console |
| Connect to Amazon OpenSearch Service | `es:ESHttp*` on the domain, plus network access to the VPC endpoint |
| Connect to OpenSearch Serverless | A data access policy that includes the role |

??? example "Example policy"
    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        { "Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::your-bucket" },
        { "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::your-bucket/*" },
        { "Effect": "Allow", "Action": "bedrock:InvokeModel",
          "Resource": "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0" }
      ]
    }
    ```

## Choosing an instance

| Workload | Instance | Settings |
| --- | --- | --- |
| Trying it out; up to ~50k chunks | `ml.t3.medium` (4 GB) | `osss.start(heap="512m")` |
| Team handbook, a few thousand PDFs | `ml.t3.large` / `ml.m5.large` (8 GB) | defaults |
| Millions of chunks, local embeddings | `ml.m5.2xlarge` or a GPU instance (`ml.g4dn.xlarge`) | `heap="4g"` |

!!! tip "Embeddings on CPU are the slow part"
    For large semantic indexes, use a GPU instance (sentence-transformers uses it automatically) or a Bedrock model.

## No internet access (VPC-only)

If the notebook can't reach the internet:

1. **Use a managed domain.** `osss.connect("https://vpc-…es.amazonaws.com")` works over your VPC endpoint.
2. **Or copy OpenSearch in yourself.** Download `opensearch-min-3.9.0-linux-x64.tar.gz` (or the full `opensearch-3.9.0-linux-x64.tar.gz` for semantic search) from [opensearch.org](https://opensearch.org/downloads.html), put it in `$OSSS_HOME/downloads/`, and `osss.start()` will use it.
3. Install osss itself from a wheel or your private package index, e.g. `pip install osss-0.1.0-py3-none-any.whl`.

## Cleaning up

Stopping the notebook stops OpenSearch too. To free memory without stopping the notebook:

```python
osss.stop()
```

To remove everything osss downloaded or created:

```python
osss.LocalServer().uninstall()
```

<div class="next" markdown>
[Troubleshooting →](troubleshooting.md){ .md-button .md-button--primary }
</div>
