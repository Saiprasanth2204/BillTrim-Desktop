"""
SMS Service for BillTrim Desktop

Uses MessageBot API for sending SMS notifications.
"""
from typing import Optional
from sqlalchemy.orm import Session

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from app.core.logging_config import get_logger
from app.core.config import settings

logger = get_logger("sms_service")


def format_phone_number(phone: str) -> str:
    """
    Format phone number for MessageBot API (10 digits for India).
    
    Args:
        phone: Phone number string (may include spaces, dashes, etc.)
    
    Returns:
        Formatted phone number (10 digits, no country code)
    """
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # If number starts with 0, remove it
    if digits.startswith('0'):
        digits = digits[1:]
    
    # If number starts with country code (91), remove it
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    
    # Return 10 digits (MessageBot expects Indian numbers without country code)
    return digits[:10]


def send_sms_via_messagebot(to: str, message: str, sender_id: Optional[str] = None) -> bool:
    """
    Send SMS via MessageBot API.
    
    Args:
        to: Recipient phone number (10 digits)
        message: SMS message content
        sender_id: Sender ID to use (if None, uses default from settings)
    
    Returns:
        bool: True if SMS was sent successfully, False otherwise
    """
    try:
        if requests is None:
            logger.warning("Cannot send SMS: 'requests' module not installed. Install with: pip install requests")
            return False
        # Check if SMS is enabled
        if not settings.SMS_ENABLED:
            logger.debug("SMS is disabled in settings")
            return False
        
        # Check if MessageBot is configured
        if not settings.MESSAGEBOT_API_TOKEN:
            logger.warning("MessageBot API token not configured. Cannot send SMS.")
            return False
        
        # Use provided sender_id or fallback to default from settings
        final_sender_id = sender_id or settings.MESSAGEBOT_SENDER_ID
        
        if not final_sender_id:
            logger.warning("MessageBot Sender ID not configured. Cannot send SMS.")
            return False
        
        # Format phone number
        formatted_phone = format_phone_number(to)
        
        if len(formatted_phone) != 10:
            logger.warning(f"Invalid phone number format: {to} (formatted: {formatted_phone})")
            return False
        
        # MessageBot API endpoint
        api_url = "https://api.messagebot.in/v1/sms"
        
        # Prepare request headers
        headers = {
            "Authorization": f"Bearer {settings.MESSAGEBOT_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Prepare request payload
        payload = {
            "to": formatted_phone,
            "senderId": final_sender_id,
            "message": message
        }
        
        # Send SMS
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            response_data = response.json()
            logger.info(
                f"SMS sent successfully via MessageBot to {formatted_phone}",
                extra={
                    "phone": formatted_phone,
                    "sender_id": final_sender_id,
                    "response": response_data
                }
            )
            return True
        else:
            logger.error(
                f"MessageBot API error: {response.status_code} - {response.text}",
                extra={
                    "phone": formatted_phone,
                    "status_code": response.status_code,
                    "response": response.text
                }
            )
            return False
            
    except Exception as e:
        if requests is not None and isinstance(e, requests.exceptions.RequestException):
            logger.error(
                f"Network error while sending SMS via MessageBot: {str(e)}",
                exc_info=True,
                extra={"phone": to}
            )
        else:
            logger.error(
                f"Error in send_sms_via_messagebot: {str(e)}",
                exc_info=True,
                extra={"phone": to}
            )
        return False


def send_appointment_confirmation_sms(appointment, db: Session) -> None:
    """
    Send SMS confirmation for an appointment (synchronous).
    
    Args:
        appointment: Appointment model instance with loaded relationships
        db: Database session
    """
    try:
        if not appointment or not appointment.customer:
            logger.warning("Cannot send SMS: appointment or customer not found")
            return
        
        customer_name = appointment.customer.name
        customer_phone = appointment.customer.phone
        
        if not customer_phone:
            logger.warning(f"Cannot send SMS: customer {appointment.customer_id} has no phone number")
            return
        
        # Format appointment date
        appointment_date = appointment.appointment_date
        if appointment_date.tzinfo:
            # Convert to local time for display (assuming IST)
            from datetime import timezone, timedelta
            ist = timezone(timedelta(hours=5, minutes=30))
            appointment_date_local = appointment_date.astimezone(ist)
        else:
            appointment_date_local = appointment_date
        
        appointment_date_str = appointment_date_local.strftime("%d %b %Y")
        appointment_time_str = appointment_date_local.strftime("%I:%M %p")
        
        staff_name = appointment.staff.name if appointment.staff else "our staff"
        
        # Get service names
        service_names = []
        if appointment.services:
            for appt_service in appointment.services:
                if appt_service.service:
                    service_name = appt_service.service.name
                    if appt_service.quantity > 1:
                        service_name += f" (x{appt_service.quantity})"
                    service_names.append(service_name)
        
        services_text = ", ".join(service_names) if service_names else "services"
        
        # Format SMS message (keeping it concise for SMS)
        message = (
            f"Hi {customer_name}, your appointment with {staff_name} "
            f"is confirmed on {appointment_date_str} at {appointment_time_str}. "
            f"Services: {services_text}. Thank you!"
        )
        
        # Check if SMS is enabled for this company (salon)
        sms_enabled = False
        sender_id = None
        if appointment.company_id:
            from app.models.company import Company
            company = db.query(Company).filter(Company.id == appointment.company_id).first()
            if company:
                sms_enabled = company.sms_enabled
                sender_id = company.sender_id
        
        # Only send SMS if enabled for this salon
        if not sms_enabled:
            logger.info(
                f"SMS skipped for appointment {appointment.id} - SMS not enabled for salon",
                extra={
                    "appointment_id": appointment.id,
                    "company_id": appointment.company_id
                }
            )
            return
        
        # Send SMS via MessageBot with company-specific sender ID
        success = send_sms_via_messagebot(customer_phone, message, sender_id=sender_id)
        
        if success:
            logger.info(
                f"SMS sent successfully for appointment {appointment.id}",
                extra={
                    "appointment_id": appointment.id,
                    "customer_id": appointment.customer_id,
                    "customer_phone": customer_phone,
                    "message": message
                }
            )
        else:
            logger.warning(
                f"SMS sending failed for appointment {appointment.id}",
                extra={
                    "appointment_id": appointment.id,
                    "customer_id": appointment.customer_id,
                    "customer_phone": customer_phone
                }
            )
        
    except Exception as e:
        logger.error(
            f"Error in send_appointment_confirmation_sms: {str(e)}",
            exc_info=True,
            extra={"appointment_id": appointment.id if appointment else None}
        )
        raise


def send_appointment_confirmation_sms_async(appointment_id: int) -> None:
    """
    Send SMS confirmation for an appointment (asynchronous via Celery).
    
    Args:
        appointment_id: ID of the appointment
    """
    try:
        # In desktop app, just log instead of queuing Celery task
        logger.info(
            f"SMS (stub async): Would queue SMS task for appointment {appointment_id}",
            extra={"appointment_id": appointment_id}
        )
        
        # In production with Celery, you would do:
        # from app.celery_app import celery_app
        # send_appointment_confirmation_sms_task.delay(appointment_id)
        
    except Exception as e:
        logger.error(
            f"Error in send_appointment_confirmation_sms_async: {str(e)}",
            exc_info=True,
            extra={"appointment_id": appointment_id}
        )
        raise


def send_invoice_sms(invoice, db: Session) -> None:
    """
    Send SMS notification for invoice (synchronous).
    
    Args:
        invoice: Invoice model instance with loaded relationships
        db: Database session
    """
    try:
        if not invoice or not invoice.customer:
            logger.warning("Cannot send SMS: invoice or customer not found")
            return
        
        customer_name = invoice.customer.name
        customer_phone = invoice.customer.phone
        
        if not customer_phone:
            logger.warning(f"Cannot send SMS: customer {invoice.customer_id} has no phone number")
            return
        
        invoice_number = invoice.invoice_number
        total_amount = float(invoice.total_amount) / 100  # Convert from paise to rupees
        
        # Format SMS message
        message = (
            f"Hi {customer_name}, your invoice #{invoice_number} "
            f"amounting to ₹{total_amount:.2f} has been generated. Thank you!"
        )
        
        # Check if SMS is enabled for this company (salon)
        sms_enabled = False
        sender_id = None
        if invoice.company_id:
            from app.models.company import Company
            company = db.query(Company).filter(Company.id == invoice.company_id).first()
            if company:
                sms_enabled = company.sms_enabled
                sender_id = company.sender_id
        
        # Only send SMS if enabled for this salon
        if not sms_enabled:
            logger.info(
                f"SMS skipped for invoice {invoice.id} - SMS not enabled for salon",
                extra={
                    "invoice_id": invoice.id,
                    "company_id": invoice.company_id
                }
            )
            return
        
        # Send SMS via MessageBot with company-specific sender ID
        success = send_sms_via_messagebot(customer_phone, message, sender_id=sender_id)
        
        if success:
            logger.info(
                f"SMS sent successfully for invoice {invoice.id}",
                extra={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice_number,
                    "customer_id": invoice.customer_id,
                    "customer_phone": customer_phone,
                    "total_amount": total_amount,
                    "message": message
                }
            )
        else:
            logger.warning(
                f"SMS sending failed for invoice {invoice.id}",
                extra={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice_number,
                    "customer_id": invoice.customer_id,
                    "customer_phone": customer_phone
                }
            )
        
    except Exception as e:
        logger.error(
            f"Error in send_invoice_sms: {str(e)}",
            exc_info=True,
            extra={"invoice_id": invoice.id if invoice else None}
        )
        raise


def send_invoice_sms_async(invoice_id: int) -> None:
    """
    Send SMS notification for invoice (asynchronous via Celery).
    
    Args:
        invoice_id: ID of the invoice
    """
    try:
        # In desktop app, just log instead of queuing Celery task
        logger.info(
            f"SMS (stub async): Would queue SMS task for invoice {invoice_id}",
            extra={"invoice_id": invoice_id}
        )
        
        # In production with Celery, you would do:
        # from app.celery_app import celery_app
        # send_invoice_sms_task.delay(invoice_id)
        
    except Exception as e:
        logger.error(
            f"Error in send_invoice_sms_async: {str(e)}",
            exc_info=True,
            extra={"invoice_id": invoice_id}
        )
        raise
