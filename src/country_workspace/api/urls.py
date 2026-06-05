from rest_framework.routers import SimpleRouter

from .views import HopeRdiViewSet


app_name = "api"

router = SimpleRouter()
router.register("hope-rdis", HopeRdiViewSet, basename="hope-rdi")

urlpatterns = router.urls
