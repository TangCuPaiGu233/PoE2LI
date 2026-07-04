from app.services.pricing_service import PricingService
from app.api.pricing import router
from app.tasks.worker import refresh_currency_rates_task
from app.tasks import celery_app
print('imports ok')
