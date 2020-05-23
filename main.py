import json
import os
from datetime import datetime, timedelta, timezone
import jwt
import requests
from jinja2 import Environment, PackageLoader, FileSystemLoader

BASE_URL = "https://api.zoom.us/v2"
PAGE_SIZE = 100
TOKEN_EXP = 5  # seconds


def get_config():
    with open('../config.json') as f:
        config_json = json.load(f)
        return config_json


def get_zoom_credentials(config_json):
    creds = config_json["parameters"]["zoom_credentials"]
    key = creds["api_key"]
    secret = creds["api_secret"]
    return key, secret


def create_jwt(key, secret, algorythm, exp_seconds):
    header = dict(alg=algorythm, typ="JWT")

    exp_epoch = datetime.utcnow() + timedelta(seconds=exp_seconds)

    payload = dict(iss=key, exp=exp_epoch)

    encoded = jwt.encode(payload=payload, headers=header, algorithm=algorythm, key=secret)
    # decoded = jwt.decode(encoded, secret, algorithms='HS256')
    return encoded


def get_response(endpoint, page_number):
    jwt_token = create_jwt(API_KEY, API_SECRET, 'HS256', 10)

    headers = {'authorization': 'Bearer ' + jwt_token.decode()}
    querystring = {"page_number": page_number, "page_size": PAGE_SIZE}
    url_request = BASE_URL + endpoint
    print(url_request)

    response = requests.request("GET", url_request, headers=headers, params=querystring)
    response_json = response.json()
    return response_json


def collect_users():
    endpoint = "/users"
    page_number = 1

    response_json = get_response(endpoint=endpoint, page_number=page_number)
    users_info = list()

    while True:
        print('request ', page_number)
        for user in response_json['users']:
            user_info = {
                "user_id": user['id'],
                "first_name": user["first_name"],
                "last_name": user["last_name"],
                "email": user["email"],
                "type": user["type"]
            }
            users_info.append(user_info)

        if response_json["page_number"] < response_json["page_count"]:
            page_number += 1
            response_json = get_response(endpoint=endpoint, page_number=page_number)
        else:
            break

    return users_info


def check_date(webinar_time):
    datetime_utc = datetime.strptime(webinar_time, "%Y-%m-%dT%H:%M:%S%z")
    datetime_now = datetime.now(timezone.utc)

    if datetime_utc > datetime_now:
        return True


def collect_future_webinars_info(user_id):
    endpoint = "/users/" + user_id + "/webinars"
    page_number = 1
    response_json = get_response(endpoint=endpoint, page_number=page_number)
    webinars_info = list()

    while True:
        print('request ', page_number)
        for webinar in response_json["webinars"]:
            if check_date(webinar["start_time"]):
                webinar_info = {
                    "webinar_id": str(webinar["id"]),
                    "topic": webinar["topic"],
                    "start_time": webinar["start_time"],
                    "timezone": webinar["timezone"]
                }
                webinars_info.append(webinar_info)

        if response_json["page_number"] < response_json["page_count"]:
            page_number += 1
            response_json = get_response(endpoint=endpoint, page_number=page_number)
        else:
            break

    return webinars_info


def get_number_registrants(webinar_id):
    endpoint = "/webinars/" + webinar_id + "/registrants"
    page_number = 1

    response_json = get_response(endpoint=endpoint, page_number=page_number)
    num_registrants = len(response_json["registrants"])

    while True:
        if response_json["page_number"] < response_json["page_count"]:
            page_number += 1
            response_json = get_response(endpoint=endpoint, page_number=page_number)
            num_registrants += len(response_json["registrants"])
        else:
            break

    return num_registrants


def get_enriched_webinars_info(user_id):
    webinars_info = collect_future_webinars_info(user_id)
    for webinar in webinars_info:
        webinar["num_registrants"] = get_number_registrants(webinar["webinar_id"])
    return webinars_info


def send_slack(webhook_url, slack_data):

    # Set the webhook_url to the one provided by Slack when you create the webhook at https://my.slack.com/services/new/incoming-webhook/
    #webhook_url = webhook_url
    #slack_data = slack_data

    response = requests.post(
        webhook_url, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'}
    )

    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )


if __name__ == "__main__":
    config = get_config()
    API_KEY, API_SECRET = get_zoom_credentials(config)
    WEBHOOK_URL = config["parameters"]["slack_credentials"]["slack_webhook"]

    webinars_consolidated = []
    for zoom_user in collect_users():
        if zoom_user["type"] == 2:
            webinars_data = get_enriched_webinars_info(zoom_user["user_id"])
            webinars_consolidated += webinars_data

    THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    templateLoader = FileSystemLoader(searchpath=THIS_DIR)
    env = Environment(loader=templateLoader)
    env.filters['jsonify'] = json.dumps
    template = env.get_template('template.txt')

    slack_data = template.render(webinars=webinars_consolidated)
    send_slack(WEBHOOK_URL, json.loads(slack_data))

