import qrcode
import base64
import uuid
from io import BytesIO
from datetime import datetime
import pytz
import logging

from app import supabase

IST = pytz.timezone('Asia/Kolkata')

def generate_package_qr(order_id):
    try:
        timestamp = datetime.now(IST).strftime("%Y%m%d%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        qr_data = f"TRACKIT_PACKAGE_{order_id}_{timestamp}_{unique_id}"
        logging.info(f"Generated package QR code for order {order_id}: {qr_data}")
        return qr_data
    except Exception as e:
        logging.error(f"Error generating package QR code: {str(e)}")
        return None

def generate_customer_delivery_qr(order_id, customer_id):
    try:
        timestamp = datetime.now(IST).strftime("%Y%m%d%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        qr_data = f"TRACKIT_CUSTOMER_DELIVERY_{order_id}_{customer_id}_{timestamp}_{unique_id}"
        logging.info(f"Generated customer delivery QR code for order {order_id}: {qr_data}")
        return qr_data
    except Exception as e:
        logging.error(f"Error generating customer delivery QR code: {str(e)}")
        return None

def get_qr_image_data(qr_data):
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=16,
            border=2,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        logging.error(f"Error creating QR image: {str(e)}")
        return None

def validate_qr_code(qr_data, scanned_by_user_id):
    """
    Implements the full workflow:
    - 1st package scan: dispatched
    - 2nd package scan: in_transit
    - 3rd package scan: out_for_delivery + generate delivery QR
    - scan delivery QR: delivered
    """
    try:
        if qr_data.startswith("TRACKIT_PACKAGE_"):
            parts = qr_data.split("_")
            if len(parts) >= 3 and parts[2].isdigit():
                order_id = int(parts[2])
                order_resp = supabase.table("orders").select("*").eq("id", order_id).single().execute()
                order = order_resp.data
                if not order:
                    return {'success': False, 'error': 'Order not found.'}

                scan_count = order.get('qr_scan_count', 0) + 1
                update_dict = {'qr_scan_count': scan_count}

                # Status workflow
                if scan_count == 1:
                    new_status = 'dispatched'
                elif scan_count == 2:
                    new_status = 'in_transit'
                elif scan_count == 3:
                    new_status = 'out_for_delivery'
                    # Generate delivery QR
                    delivery_qr = generate_customer_delivery_qr(order_id, order['customer_id'])
                    update_dict['delivery_qr_code'] = delivery_qr
                else:
                    return {'success': False, 'error': 'Package already scanned 3 times.'}

                update_dict['status'] = new_status
                supabase.table("orders").update(update_dict).eq("id", order_id).execute()
                updated_order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data

                res = {'success': True, 'order': updated_order, 'scan_type': 'package'}
                if scan_count == 3:
                    res['delivery_qr_generated'] = True
                return res
            else:
                logging.error(f"Malformed PACKAGE QR code: {qr_data}")
                return {'success': False, 'error': 'Malformed QR code.'}

        elif qr_data.startswith("TRACKIT_CUSTOMER_DELIVERY_"):
            parts = qr_data.split("_")
            # Should be at least 6: TRACKIT, CUSTOMER, DELIVERY, <order_id>, <customer_id>, <timestamp>, <unique_id>
            if len(parts) >= 6 and parts[3].isdigit():
                order_id = int(parts[3])
                order_resp = supabase.table("orders").select("*").eq("id", order_id).single().execute()
                order = order_resp.data
                if not order:
                    return {'success': False, 'error': 'Order not found.'}
                if order['status'] != 'out_for_delivery':
                    return {'success': False, 'error': 'Order not ready for delivery confirmation.'}
                supabase.table("orders").update({
                    'status': 'delivered',
                    'delivered_at': datetime.now(IST).isoformat()
                }).eq("id", order_id).execute()
                updated_order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
                return {'success': True, 'order': updated_order, 'scan_type': 'delivery'}
            else:
                logging.error(f"Malformed CUSTOMER_DELIVERY QR code: {qr_data}")
                return {'success': False, 'error': 'Malformed Delivery QR code.'}
        else:
            logging.error(f"Invalid QR code format: {qr_data}")
            return {'success': False, 'error': 'Invalid QR code format.'}
    except Exception as e:
        logging.error(f"Error in validate_qr_code: {str(e)}; qr_data={qr_data}")
        return {'success': False, 'error': str(e)}