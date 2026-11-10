# Troubleshooting

Start with the built-in check. It catches most problems:

```bash
osss doctor
```

Add `OSSS_DEBUG=1` to any CLI command for a full traceback. In the app, open **Traceback** under any error message.

## Starting OpenSearch

??? question "“OpenSearch exited during startup” mentioning memory"
    The machine doesn't have enough free memory for the heap. Use a smaller one:
    ```python
    osss.start(heap="512m")
    ```

??? question "Port 9200 is already in use"
    osss automatically uses the next free port and remembers it. To choose one yourself: `osss.start(port=9250)`.

??? question "The download fails or the notebook has no internet"
    Copy the OpenSearch tarball into `$OSSS_HOME/downloads/` (see [SageMaker → No internet access](sagemaker.md#no-internet-access-vpc-only)), or connect to an existing cluster with `osss.connect(url)`.

??? question "Docker pull is rate-limited"
    osss pulls from AWS ECR Public first and falls back to Docker Hub. If both fail, `backend="auto"` falls back to the tarball on Linux. You can also force it: `osss.start(backend="tarball")`.

??? question "“…is not accessible to other users” when running as root"
    OpenSearch runs as `nobody` when you're root, so its files must be outside `/root`. Set a different location:
    ```python
    import os; os.environ["OSSS_HOME"] = "/opt/osss"
    ```

??? question "Something else is wrong with the server"
    Look at the logs: `osss logs -n 200`, or **⚙ Server → Logs** in the app. As a last resort, reset everything (this deletes your indexes):
    ```python
    osss.LocalServer().uninstall()
    ```

## Indexing

??? question "Some files were skipped"
    The build report says why for each one. Common reasons:

    - **unsupported type**: images, archives and other binary files.
    - **no extractable text (scanned PDF?)**: the PDF is an image. Run OCR first (e.g. `ocrmypdf`, or Amazon Textract).
    - **larger than 100 MB**: raise `max_file_mb`.
    - **needs `pyarrow`**: install the extra with `pip install "osss[parquet] @ git+…"`.

??? question "“Index … already exists”"
    Pass `recreate=True` to rebuild it, choose another name, or add files with `cluster.index(name).add(source)`.

??? question "S3: AccessDenied or NoCredentialsError"
    The notebook role (or your AWS profile) needs `s3:ListBucket` and `s3:GetObject`. Check what you're using with `aws sts get-caller-identity`.

??? question "Indexing is slow"
    - Many small S3 files: raise `workers=16` or `32`.
    - Semantic indexes: embedding is the slow step. Use a GPU instance or Bedrock, or a smaller model.
    - Big PDFs: text extraction is CPU-bound. That's expected.

## Searching

??? question "No results for something I know is there"
    - Check the index has the file: `idx.search("", filters={"path": "folder/file.pdf"})`.
    - Try `fuzzy=True` for typos, or `mode="semantic"` for different wording.
    - With **Match all words** (`operator="and"`), every word must appear.

??? question "A metadata filter returns nothing, or hits have no metadata"
    String values are case-sensitive, numbers must be filtered as numbers (`2024`, not `"2024"`), and a sidecar must be named after the full file name (`report.pdf.metadata.json`). See [Metadata & filtering → Troubleshooting](guide/metadata.md#troubleshooting).

??? question "Semantic / Hybrid isn't offered"
    The index was built without embeddings. Rebuild it with `semantic=True`; see [Semantic & hybrid search](guide/semantic.md).

??? question "“This index was built with the custom embedder …”"
    The index uses a function you provided. Register it again in this session:
    ```python
    osss.register_embedder(my_embedder, "custom")
    ```

## The app

??? question "The app shows as text instead of widgets"
    The front end needs `ipywidgets`. In JupyterLab 3+ and SageMaker Studio it's built in. Make sure `ipywidgets` is installed in the **kernel's** environment, then reload the browser tab.

??? question "Buttons don't respond after a kernel restart"
    Widgets belong to the kernel that created them. Re-run `osss.ui()`.

Still stuck? [Open an issue](https://github.com/utkarsh5026/osss/issues) with the output of `osss doctor`.
