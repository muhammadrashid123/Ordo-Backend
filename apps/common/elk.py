from urllib.parse import urlencode


def _make_elk_link(task_id):
    base_url = "https://elk.joinordo.com/app/discover#/"
    params = {
        "_g": "(filters:!(),refreshInterval:(pause:!t,value:60000))",
        "_a": "(columns:!(message),"
        "filters:!(),"
        "index:'24ffa3c2-af6c-4d63-888f-15ee771cb8a9',"
        "interval:auto,"
        "query:("
        "language:kuery,"
        f"query:'task_id: \"{task_id}\"'"
        "),"
        "sort:!(!('@timestamp',desc)))",
    }
    query_params = urlencode(params)
    return f"{base_url}?{query_params}"
