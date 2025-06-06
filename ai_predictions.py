import pandas as pd
import numpy as np
from sklearn.svm import SVC
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from datetime import datetime
import pytz
import logging

from app import supabase

IST = pytz.timezone('Asia/Kolkata')

class OrderPredictor:
    def __init__(self):
        self.window_time_encoder = LabelEncoder()
        self.delivery_speed_encoder = LabelEncoder()
        self.day_encoder = LabelEncoder()
        self.vendor_encoder = LabelEncoder()
        self.model_window = None
        self.model_speed = None
        self.is_trained = False

    def prepare_features(self, customer_id):
        try:
            response = supabase.table("orders").select("*").eq("customer_id", customer_id).eq("status", "delivered").execute()
            history = response.data or []

            if len(history) < 5:
                return None

            data = []
            for record in history:
                created_at = record.get("created_at")
                dt = datetime.fromisoformat(created_at)
                data.append({
                    'customer_id': record["customer_id"],
                    'vendor_id': record["vendor_id"],
                    'window_time': record["window_time"],
                    'delivery_speed': record["delivery_speed"],
                    'order_day': dt.strftime("%A").lower(),
                    'order_hour': dt.hour
                })

            df = pd.DataFrame(data)

            now = datetime.now(IST)
            current_day = now.strftime('%A').lower()
            current_hour = now.hour

            df_encoded = df.copy()
            df_encoded['window_time_encoded'] = self.window_time_encoder.fit_transform(df['window_time'])
            df_encoded['delivery_speed_encoded'] = self.delivery_speed_encoder.fit_transform(df['delivery_speed'])
            df_encoded['day_encoded'] = self.day_encoder.fit_transform(df['order_day'])
            df_encoded['vendor_encoded'] = self.vendor_encoder.fit_transform(df['vendor_id'].astype(str))

            features = ['vendor_encoded', 'day_encoded', 'order_hour']
            X = df_encoded[features].values
            y_window = df_encoded['window_time_encoded'].values
            y_speed = df_encoded['delivery_speed_encoded'].values

            return X, y_window, y_speed, current_day, current_hour

        except Exception as e:
            logging.error(f"Error preparing features: {str(e)}")
            return None

    def train_models(self, customer_id):
        try:
            data = self.prepare_features(customer_id)
            if data is None:
                return False

            X, y_window, y_speed, _, _ = data

            if len(X) < 5:
                return False

            self.model_window = SVC(kernel='rbf', probability=True, random_state=42)
            self.model_speed = SVC(kernel='rbf', probability=True, random_state=42)

            if len(X) > 10:
                X_train, X_test, y_window_train, y_window_test = train_test_split(
                    X, y_window, test_size=0.2, random_state=42
                )
                _, _, y_speed_train, y_speed_test = train_test_split(
                    X, y_speed, test_size=0.2, random_state=42
                )

                self.model_window.fit(X_train, y_window_train)
                self.model_speed.fit(X_train, y_speed_train)
            else:
                self.model_window.fit(X, y_window)
                self.model_speed.fit(X, y_speed)

            self.is_trained = True
            return True

        except Exception as e:
            logging.error(f"Error training models: {str(e)}")
            return False

    def predict(self, customer_id, vendor_id=None):
        try:
            if not self.is_trained:
                if not self.train_models(customer_id):
                    return None

            now = datetime.now(IST)
            current_day = now.strftime('%A').lower()
            current_hour = now.hour

            # Use vendor_id, or most frequent from history if not provided
            if vendor_id is None:
                response = supabase.table("orders").select("vendor_id").eq("customer_id", customer_id).eq("status", "delivered").execute()
                history = response.data or []
                if not history:
                    return None
                vendor_counts = {}
                for record in history:
                    vid = str(record["vendor_id"])
                    vendor_counts[vid] = vendor_counts.get(vid, 0) + 1
                vendor_id = max(vendor_counts, key=vendor_counts.get)
            vendor_id = str(vendor_id)

            try:
                day_encoded = self.day_encoder.transform([current_day])[0]
            except:
                day_encoded = 0

            try:
                vendor_encoded = self.vendor_encoder.transform([vendor_id])[0]
            except:
                vendor_encoded = 0

            features = np.array([[vendor_encoded, day_encoded, current_hour]])

            window_pred = self.model_window.predict(features)[0]
            speed_pred = self.model_speed.predict(features)[0]

            window_proba = self.model_window.predict_proba(features)[0]
            speed_proba = self.model_speed.predict_proba(features)[0]

            window_time = self.window_time_encoder.inverse_transform([window_pred])[0]
            delivery_speed = self.delivery_speed_encoder.inverse_transform([speed_pred])[0]

            window_confidence = float(np.max(window_proba))
            speed_confidence = float(np.max(speed_proba))

            return {
                'window_time': window_time,
                'delivery_speed': delivery_speed,
                'window_confidence': window_confidence,
                'speed_confidence': speed_confidence
            }

        except Exception as e:
            logging.error(f"Error making predictions: {str(e)}")
            return None

predictor = OrderPredictor()

def get_ai_predictions(customer_id, vendor_id=None):
    try:
        # Fetch user from Supabase and check eligibility
        user_resp = supabase.table("users").select("*").eq("id", customer_id).single().execute()
        user = user_resp.data
        if not user or user.get("successful_orders", 0) < 5:
            return None

        predictions = predictor.predict(customer_id, vendor_id)

        if predictions:
            window_descriptions = {
                '9am-12pm': '9 AM - 12 PM (Morning)',
                '12pm-4pm': '12 PM - 4 PM (Afternoon)',
                '5pm-9pm': '5 PM - 9 PM (Evening)',
                '9pm-9am': '9 PM - 9 AM (Night/Early Morning)'
            }
            speed_descriptions = {
                'express': 'Express - Same Day Delivery',
                'regular': 'Regular - 1-7 Days'
            }
            predictions['window_description'] = window_descriptions.get(
                predictions['window_time'], predictions['window_time']
            )
            predictions['speed_description'] = speed_descriptions.get(
                predictions['delivery_speed'], predictions['delivery_speed']
            )
            predictions['window_confidence_percent'] = int(predictions['window_confidence'] * 100)
            predictions['speed_confidence_percent'] = int(predictions['speed_confidence'] * 100)

        return predictions

    except Exception as e:
        logging.error(f"Error getting AI predictions: {str(e)}")
        return None