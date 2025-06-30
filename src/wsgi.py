from main import create_app
from startup.services import create_app_services

app = create_app()
create_app_services(app)
