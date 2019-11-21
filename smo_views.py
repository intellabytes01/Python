import datetime
import copy
import csv
from rest_framework.views import APIView
from rest_framework.parsers import FileUploadParser
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_jwt import authentication
from django.utils import timezone
from django.conf import settings
from core.models import Case
from smo.serializers import (
    CaseSerializer,
    MoveAbortSerializer, MoveStartEndSerializer,
    CustomTokenObtainPairSerializer, 
    DisclaimerSerializer, CustomFCMDeviceSerializer, NotificationSerializer,
    IssueSerializer, IssueDetailSerializer, IssueCloseSerializer, CSVSerializer,
    PeriodSerializer, AddRemarkSerializer
    )
from smo.permissions import MoveUpdatePermission, ManagerPermission
from rest_framework import serializers
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.views import TokenObtainPairView
from utility.helper import Base64ToImageConverter
from fcm_django.models import FCMDevice
from django.db.models import Q
from .models import Issue
from io import StringIO
from core.forms import CaseFormForSmo



class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Takes a set of user credentials and returns an access and refresh JSON web
    token pair to prove the authentication of those credentials.
    """
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super(CustomTokenObtainPairView, self).post(request, *args, **kwargs)

        serializer = self.get_serializer(data=request.data)


        try:
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
        except TokenError as e:
            raise serializers.ValidationError({"error": "Role not matched."})


        return response


class CaseListAPIView(generics.ListAPIView):
    model = Case
    serializer_class = CaseSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    queryset = Case.crmobjects.filter(
        Q(move_date=timezone.now().date())
        | Q(move_started=True,
            move_ended=False)
    ).exclude(move_aborted=True).exclude(move_started=True, move_ended=True)


class CompletedCaseListWithPeriodAPIView(APIView):
    """completed case list for a specified period"""
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]

    def post(self, request, *args, **kwargs):
        serializer = PeriodSerializer(data=request.data)
        if serializer.is_valid():
            queryset = Case.crmobjects.filter(
                move_ended_date__gte=serializer.validated_data['from_date'],
                move_ended_date__lte=serializer.validated_data['to_date']
                ).exclude(move_aborted=True).exclude(move_ended=False)
            return Response(CaseSerializer(queryset, many=True).data)

        return Response(serializer.errors)


class NewInCompletedCaseListWithPeriodAPIView(APIView):
    """incompleted or case list for a specified period"""
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]

    def post(self, request, *args, **kwargs):
        serializer = PeriodSerializer(data=request.data)
        if serializer.is_valid():
            queryset = Case.crmobjects.filter(
                move_date__gte=serializer.validated_data['from_date'],
                move_date__lte=serializer.validated_data['to_date']
                ).exclude(move_ended=True).exclude(move_aborted=True)
            return Response(CaseSerializer(queryset, many=True).data)

        return Response(serializer.errors)


class AbortedCaseListWithPeriodAPIView(APIView):
    """incompleted or case list for a specified period"""
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]

    def post(self, request, *args, **kwargs):
        serializer = PeriodSerializer(data=request.data)
        if serializer.is_valid():
            queryset = Case.crmobjects.filter(
                move_date__gte=serializer.validated_data['from_date'],
                move_date__lte=serializer.validated_data['to_date'],
                move_aborted=True,
                )
            return Response(CaseSerializer(queryset, many=True).data)

        return Response(serializer.errors)


class IncompleteCaseListAPIView(generics.ListAPIView):
    model = Case
    serializer_class = CaseSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    queryset = Case.crmobjects.filter(
        move_started=True,
        move_ended=False
    ).exclude(move_aborted=True)


class MoveStartView(generics.UpdateAPIView):
    queryset = Case.crmobjects.all()
    serializer_class = MoveStartEndSerializer

    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    def perform_update(self, serializer):
        obj = self.get_object()

        imagestr = serializer.validated_data['imagestr']
        serializer.save()
        
        if obj.move_started:
            raise serializers.ValidationError({
                "msz":"Move Already started",
                })

        f = Base64ToImageConverter(
            imagestr=imagestr,
            filename=settings.MEDIA_ROOT+'/case/signatures/{}_sign.png'.format(str(obj.id)),
            ).convert()
        
        obj.customer_signature = '/case/signatures/' + f.split('/')[-1]
        obj.move_started = True
        obj.save()


class MoveAbortView(generics.UpdateAPIView):
    queryset = Case.crmobjects.all()
    serializer_class = MoveAbortSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]


class RemarkView(generics.UpdateAPIView):
    queryset = Case.crmobjects.all()
    serializer_class = AddRemarkSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]


class MoveEndView(MoveStartView):

    def perform_update(self, serializer):
        obj = self.get_object()

        imagestr = serializer.validated_data['imagestr']
        serializer.save()

        if obj.move_ended:
            raise serializers.ValidationError({
                "msz": "Move Already ended",
            })

        f = Base64ToImageConverter(
            imagestr=imagestr,
            filename=settings.MEDIA_ROOT + '/case/signatures/{}_signoff.png'.format(str(obj.id)),
        ).convert()

        obj.customer_signoff = '/case/signatures/' + f.split('/')[-1]
        obj.move_ended = True
        obj.save()


class DeviceCreateView(generics.CreateAPIView):
    queryset = FCMDevice.objects.all()
    serializer_class = CustomFCMDeviceSerializer

    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    def perform_create(self, serializer):

        validated_data = serializer.validated_data

        serializer.save(user=self.request.user, name=self.request.user.get_full_name())


class NotificationView(APIView):
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = NotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data['title']
        message = serializer.validated_data['message']

        try:
            devices = FCMDevice.objects.filter(user__groups__name="SMO BOT Supervisor")

            if not devices.exists():
                return Response({"msz": "no device found for supervisor"})

            data = devices.send_message(title, message)

            return Response(data)
        except:
            return Response({"status": "failed"})


class ManagerNotificationView(APIView):

    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = NotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data['title']
        message = serializer.validated_data['message']
        
        try:
            devices = FCMDevice.objects.filter(user__groups__name="SMO BOT Manager")
            if not devices.exists():
                return Response({"msz": "no device found for managers"})

            data = devices.send_message(title, message)
            return Response(data)
        except:
            return Response({"status": "failed"})


class IssueListAPIView(generics.ListCreateAPIView):
    serializer_class = IssueSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [MoveUpdatePermission]
    queryset = Issue.objects.filter(is_closed=False).order_by('-id')

    def perform_create(self, serializer):
        serializer.save(raised_by=self.request.user)


class IssueDetailAPIView(generics.RetrieveAPIView):
    serializer_class = IssueDetailSerializer
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]
    queryset = Issue.objects.filter(is_closed=False).order_by('-id')


class IssueCloseAPIView(generics.UpdateAPIView):
    serializer_class = IssueCloseSerializer
    queryset = Issue.objects.all()

    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]

    def perform_update(self, serializer):
        if self.get_object().closed_by is not None:
            raise serializers.ValidationError({
                    "msz": "issue already closed by {}".format(self.get_object().closed_by)
                })

        serializer.save(closed_by=self.request.user)


class UploadCSV(APIView):
    authentication_classes = [authentication.JSONWebTokenAuthentication, JWTAuthentication]
    permission_classes = [ManagerPermission]
    # parser_classes = [FileUploadParser,]

    def post(self, request, *args, **kwargs):
        serializer = CSVSerializer(data=request.data)
        context = {
            "errors": []
        }
        csvfile = request.FILES.get('csv', None)
        if serializer.is_valid(raise_exception=True):
            data = csv.DictReader(StringIO(csvfile.read().decode('utf-8')), delimiter=',')
            cases_created = 0
            for row in data:
                try:
                    data = {
                        "customer_name": row['customer_name'],
                        "contact_no": row['contact_no'],
                        "customer_email": row['customer_email'],
                        "old_location": row['old_location'],
                        "new_location": row['new_location'],
                        "move_date": row['move_date'],
                    }
                except KeyError:
                    data = None
                    context = {
                        "status": "failed",
                        "msz": "keys error in csv file",
                        "date-format": "yyyy-mm-dd",
                        "keys": ["customer_name", "customer_email", "contact_no", "old_location",
                        "new_location", "move_date"]
                    }

                    return Response(context, status=status.HTTP_400_BAD_REQUEST)

                test_data = copy.deepcopy(data)
                move_date = test_data.pop('move_date')
                case_exists = Case.objects.filter(
                    **test_data,
                    move_date=datetime.datetime.strptime(move_date, "%Y-%m-%d")
                ).exists()

                if data is not None and (not case_exists):
                    case_form = CaseFormForSmo(data)
                    if case_form.is_valid():
                        # case = Case(**data)
                        case = case_form.save(commit=False)
                        case.case_by_crm = True
                        case.save()
                        cases_created += 1
                    else:
                        context['errors'].append(case_form.errors)
                        return Response(context, status=status.HTTP_400_BAD_REQUEST)
            
            context['cases_created'] = cases_created
            return Response(context, status=status.HTTP_201_CREATED)

        return Response(context, status=status.HTTP_400_BAD_REQUEST)

