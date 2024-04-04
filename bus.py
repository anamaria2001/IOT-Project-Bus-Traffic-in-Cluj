import csv
import datetime
import json
import threading
import time
import requests
import pytz
from itertools import islice
#import os
from twilio.rest import Client
import sms

stations_array = []

def load_stations_from_json(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
        return data

def find_station_coords(station_name, stations):
    for station in stations:
        if station['station_name'].lower() == station_name.lower():
            return station['coords']
    return None

def getSchedule(station, day):
    # URL for the request
    url = 'https://ctpcj.ro/orare/csv/orar_' + station + '_' + day + '.csv'

    headers = {
        'authority': 'ctpcj.ro',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,ro-RO;q=0.8,ro;q=0.7',
        'cache-control': 'no-cache',
        'cookie': '_ga=GA1.1.439799702.1701083481; 8acd276948ff3eb4615a742e533be98c=7c968cbefb557c675655a6d1fd3cc54d; _ga_V4YDWT84EJ=GS1.1.1701091264.2.1.1701091281.0.0.0',
        'dnt': '1',
        'pragma': 'no-cache',
        'referer': 'https://ctpcj.ro/index.php/ro/tarife/informatii-abonamente-gratuite-reduse/116-categorie-ro-ro/orare-statii/1520-statia-bucium',
        'sec-ch-ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest'
    }

    response = requests.get(url, headers=headers)

    # Check if the request was successful and print the content
    if response.status_code == 200:
        # Create a CSV reader from the response text
        csv_reader = csv.reader(response.text.splitlines())

        data_array = []

        # Skip the first five lines and process the rest
        for row in islice(csv_reader, 5, None):
            time, line_number = row[0], row[1]

            # Create a dictionary and append to the array
            data_array.append({"time": time, "line_number": line_number, 'station_name': station})
        return data_array
    else:
        print(f"Request failed with status code: {response.status_code}")
        return None


def generate_weekday_timestamps(input_array, coords):
    # Define the start and end dates for the range 
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(days=30)  

    output_array = []

    # Iterate through the date range, skipping weekends
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:  
            for item in input_array:
                time_str = item['time'].strip()
                line_number = item['line_number']
                station_name = item['station_name']

                # Combine date and time
                datetime_obj = datetime.datetime.combine(current_date,
                                                         datetime.datetime.strptime(time_str, '%H:%M').time())

                # Convert to ISO 8601 format and append to output array
                output_array.append({
                    'time': datetime_obj.isoformat() + 'Z',
                    'line_number': line_number,
                    'station_name': station_name,
                    'lat': coords.get("lat"),
                    'long': coords.get("long")
                })

        # Move to the next day
        current_date += datetime.timedelta(days=1)

    return output_array


def generate_weekend_timestamps(input_array, coords, day):
    # Define the start and end dates for the range (you can adjust these as needed)
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(days=30)  # For a longer range to ensure Saturdays are included

    output_array = []

    # Iterate through the date range, selecting only Saturdays
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() == 5 + day:  # 5 corresponds to Saturday
            for item in input_array:
                time_str = item['time'].strip()  # Strip whitespace
                line_number = item['line_number']
                station_name = item['station_name']

                # Combine date and time
                datetime_obj = datetime.datetime.combine(current_date,
                                                         datetime.datetime.strptime(time_str, '%H:%M').time())

                # Convert to ISO 8601 format and append to output array
                output_array.append({
                    'time': datetime_obj.isoformat() + 'Z',
                    'line_number': line_number,
                    'station_name': station_name,
                    'lat': coords.get("lat"),
                    'long': coords.get("long")
                })

        # Move to the next day
        current_date += datetime.timedelta(days=1)

    return output_array


def generate_monthly_schedule(station, coords):
    # Generate schedules
    weekday_schedule = generate_weekday_timestamps(getSchedule(station, "lv"), coords)
    saturday_schedule = generate_weekend_timestamps(getSchedule(station, "s"), coords, 0)  # 0 for Saturday, 1 for Sunday
    sunday_schedule = generate_weekend_timestamps(getSchedule(station, "d"), coords, 1)  # 0 for Saturday, 1 for Sunday

    # Combine schedules
    combined_schedule = weekday_schedule + saturday_schedule + sunday_schedule

    # Sort by date
    sorted_schedule = sorted(combined_schedule, key=lambda x: x['time'])

    return sorted_schedule



def send_data_to_thinger(data, thinger_endpoint, access_token):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + access_token
    }

    try:
        response = requests.put(thinger_endpoint, headers=headers, data=json.dumps(data))
        response.raise_for_status()  

        return response.status_code, response.text
    except requests.exceptions.HTTPError as errh:
        print(f"Http Error: {errh}")
    except requests.exceptions.ConnectionError as errc:
        print(f"Error Connecting: {errc}")
    except requests.exceptions.Timeout as errt:
        print(f"Timeout Error: {errt}")
    except requests.exceptions.RequestException as err:
        print(f"Error: {err}")
    except json.JSONDecodeError:
        print("Failed to decode JSON. Response content:")
        print(response.text)

    return response.status_code, None



def find_closest_future_entry(schedule):
    # Define Bucharest timezone
    bucharest_tz = pytz.timezone('Europe/Bucharest')

    # Get current time in Bucharest timezone
    current_time = datetime.datetime.now(bucharest_tz)

    # Initialize an empty list for future entries
    future_entries = []

    for entry in schedule:
        # Parse each entry's time and convert it to Bucharest timezone
        entry_time_naive = datetime.datetime.fromisoformat(entry['time'].rstrip('Z'))
        entry_time_bucharest = bucharest_tz.localize(entry_time_naive)

        if entry_time_bucharest > current_time:
            future_entries.append(entry)

    # If there are no future entries, return None
    if not future_entries:
        return None

    # Sort the future entries by time and select the first one
    closest_entry = sorted(future_entries, key=lambda x: x['time'])[0]
    print(closest_entry)
    return closest_entry


def minutes_until_bucharest_time(future_date_iso_str):
    # Define Bucharest timezone
    bucharest_tz = pytz.timezone('Europe/Bucharest')

    # Parse the ISO format date
    future_date_naive = datetime.datetime.fromisoformat(future_date_iso_str.rstrip('Z'))
    future_date_bucharest = bucharest_tz.localize(future_date_naive)

    # Get current time in Bucharest timezone
    now_bucharest = datetime.datetime.now(bucharest_tz)

    # Calculate the difference in minutes
    diff = future_date_bucharest - now_bucharest
    minutes_diff = diff.total_seconds() / 60

    return max(0, minutes_diff)  # Return 0 if the date is in the past

def task_for_trr(station):
    access_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJ0b2tlbiIsInN2ciI6ImV1LWNlbnRyYWwuYXdzLnRoaW5nZXIuaW8iLCJ1c3IiOiJBbmFtYXJpYTIwMDEifQ.0-Ttnd-iapkewtCXCVFUGmyxIhr8WSwV-M2sLYRQsfE'  # Your Thinger.io access token
    station_name = station['station_name']
    station_coords = station['coords']
    station_schedule = generate_monthly_schedule(station_name, station_coords)
    while True:
        to_send = {
            "property": "next_bus",
            "value": find_closest_future_entry(station_schedule)['line_number'],
        }
        (send_data_to_thinger(to_send, 'https://eu-central.aws.thinger.io:443/v3/users/Anamaria2001/devices/orar_'+station_name+'/properties/next_bus', access_token))
        to_send = {
            "property": "next_bus_time",
            "value": minutes_until_bucharest_time(find_closest_future_entry(station_schedule)['time']),
        }
        (send_data_to_thinger(to_send, 'https://eu-central.aws.thinger.io:443/v3/users/Anamaria2001/devices/orar_'+station_name+'/properties/next_bus_time', access_token))
        time.sleep(60);
    
def task_for_sms(station):
    station_name = station['station_name']
    station_coords = station['coords']
    station_schedule = generate_monthly_schedule(station_name, station_coords)

    # Find the closest future entry
    closest_entry = find_closest_future_entry(station_schedule)

    if closest_entry:
        # Print information to console
        print(f"Next bus at {closest_entry['time']} for station {station_name}: {closest_entry['line_number']}")

        # Send SMS with the information
        client = Client(sms.account_sid, sms.auth_token)
        message_body = f"Next bus at {closest_entry['time']} for station {station_name}: {closest_entry['line_number']}"
        message = client.messages.create(
            body=message_body,
            from_='+12059315423',
            to='+40740327140'
        )
        print(message.sid)
    else:
        print(f"No future entries found for station {station_name}")

def send_monhtly_station_stream():

    stations_array = load_stations_from_json('stations.json')
    for station in stations_array:
        thread = threading.Thread(target=task_for_trr, args=(station,))
        # Start the thread
        thread.start()

def send_sms():

    stations_array = load_stations_from_json('stations.json')
    for station in stations_array:
        thread = threading.Thread(target=task_for_sms, args=(station,))
        # Start the thread
        thread.start()

send_monhtly_station_stream()
send_sms()