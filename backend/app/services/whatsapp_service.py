"""
WhatsApp Service for BillTrim Desktop

Uses Twilio WhatsApp API to send appointment confirmations via WhatsApp.
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.core.logging_config import get_logger
from app.core.config import settings

logger = get_logger("whatsapp_service")

# Try to import Twilio, but don't fail if not installed
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.warning("Twilio library not installed. WhatsApp functionality will be disabled.")


def format_phone_number(phone: str) -> str:
    """
    Format phone number for WhatsApp (E.164 format).
    Assumes Indian numbers if no country code is present.
    
    Args:
        phone: Phone number string (may include spaces, dashes, etc.)
    
    Returns:
        Formatted phone number in E.164 format (e.g., +919876543210)
    """
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # If number starts with 0, remove it
    if digits.startswith('0'):
        digits = digits[1:]
    
    # If number doesn't start with country code, assume India (+91)
    if not digits.startswith('91') and len(digits) == 10:
        digits = '91' + digits
    
    # Add + prefix
    return '+' + digits


def send_appointment_confirmation_whatsapp(appointment, db: Session) -> bool:
    """
    Send WhatsApp confirmation for an appointment (synchronous).
    
    Args:
        appointment: Appointment model instance with loaded relationships
        db: Database session
    
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    try:
        if not appointment or not appointment.customer:
            logger.warning("Cannot send WhatsApp: appointment or customer not found")
            return False
        
        # Check if WhatsApp is enabled
        if not settings.WHATSAPP_ENABLED:
            logger.debug("WhatsApp is disabled in settings")
            return False
        
        # Check if Twilio is configured
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            logger.warning("Twilio credentials not configured. Cannot send WhatsApp.")
            return False
        
        if not TWILIO_AVAILABLE:
            logger.error("Twilio library not available. Install it with: pip install twilio")
            return False
        
        customer_name = appointment.customer.name
        customer_phone = appointment.customer.phone
        
        if not customer_phone:
            logger.warning(f"Cannot send WhatsApp: customer {appointment.customer_id} has no phone number")
            return False
        
        # Format appointment details
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
        
        # Format WhatsApp message
        message = (
            f"Hi {customer_name}! 👋\n\n"
            f"Your appointment with {staff_name} is confirmed.\n\n"
            f"📅 Date: {appointment_date_str}\n"
            f"⏰ Time: {appointment_time_str}\n"
            f"💆 Services: {services_text}\n\n"
            f"Thank you for choosing us! 🙏"
        )
        
        # Format phone number
        formatted_phone = format_phone_number(customer_phone)
        
        # Send WhatsApp message via Twilio
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            
            # Twilio WhatsApp format: whatsapp:+919876543210
            whatsapp_from = f"whatsapp:{settings.TWILIO_WHATSAPP_FROM}"
            whatsapp_to = f"whatsapp:{formatted_phone}"
            
            message_response = client.messages.create(
                body=message,
                from_=whatsapp_from,
                to=whatsapp_to
            )
            
            logger.info(
                f"WhatsApp sent successfully to {formatted_phone}",
                extra={
                    "appointment_id": appointment.id,
                    "customer_id": appointment.customer_id,
                    "customer_phone": formatted_phone,
                    "message_sid": message_response.sid,
                    "status": message_response.status
                }
            )
            
            return True
            
        except Exception as twilio_error:
            logger.error(
                f"Twilio API error while sending WhatsApp: {str(twilio_error)}",
                exc_info=True,
                extra={
                    "appointment_id": appointment.id,
                    "customer_id": appointment.customer_id,
                    "customer_phone": formatted_phone,
                    "error": str(twilio_error)
                }
            )
            return False
        
    except Exception as e:
        logger.error(
            f"Error in send_appointment_confirmation_whatsapp: {str(e)}",
            exc_info=True,
            extra={"appointment_id": appointment.id if appointment else None}
        )
        return False


def send_appointment_confirmation_whatsapp_async(appointment_id: int) -> None:
    """
    Send WhatsApp confirmation for an appointment (asynchronous via Celery).
    
    Args:
        appointment_id: ID of the appointment
    """
    try:
        # In desktop app, just log instead of queuing Celery task
        logger.info(
            f"WhatsApp (async stub): Would queue WhatsApp task for appointment {appointment_id}",
            extra={"appointment_id": appointment_id}
        )
        
        # In production with Celery, you would do:
        # from app.celery_app import celery_app
        # send_appointment_confirmation_whatsapp_task.delay(appointment_id)
        
    except Exception as e:
        logger.error(
            f"Error in send_appointment_confirmation_whatsapp_async: {str(e)}",
            exc_info=True,
            extra={"appointment_id": appointment_id}
        )
        raise
