from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.forms import model_to_dict
from django.db.models import F
from django.core.mail import send_mail
from django.conf import settings
from utility import helper
from django.utils.http import urlsafe_base64_decode
from chatbot.models import Statement, Choice, Bot
from core.forms import AddressForm, CaseForm, CaseImageForm
from core.models import Case, CaseToken, CaseRoom, YoloObject
import numpy as np, json, requests, threading, cv2, random
from django.utils.crypto import get_random_string
# Create your views here.


class SceBotView(View):
    """sce bot main view"""
    @staticmethod
    def get(request):
        bot = get_object_or_404(Bot, name='sce')
        context = {
            "bot_id": bot.id,
            "recipient_id": get_random_string(6).lower(),
        }
        return render(request, 'chatbot/chatbot.html', context)


class GetStatementView(View):
    """sce bot get statement view for ajax call"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(GetStatementView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request):
        obj_id = request.POST.get('id', '')
        bot_id = request.POST.get('bot_id', None)
        parsing = request.POST.get('parsing', 'statement')

        if obj_id != '':
            if parsing == 'choice':
                choice = Choice.objects.get(id=obj_id)
                statement = choice.redirect_statement

            elif parsing == 'direct':
                statement = Statement.objects.get(id=obj_id)

            else:
                statement = Statement.objects.get(prev_statement__id=obj_id)

        else:
            statement = Statement.objects.filter(is_first=True).last()
            if bot_id not in [None, '']:
                statement = Statement.objects.filter(bot_id=bot_id, is_first=True).last()

        return JsonResponse(model_to_dict(statement))


class GetChoicesView(View):
    """sce bot get choce view for ajax call"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(GetChoicesView, self).dispatch(request, *args, **kwargs)

    def post(self, request):
        statement_id = request.POST.get('id', '')

        if id != '':
            choices = Choice.objects.filter(statement__id=statement_id)
            if not choices.exists():
                statement = Statement.objects.get(id=statement_id)
                if statement.get_choices_from is not None:
                    choices = Choice.objects.filter(statement_id=statement.get_choices_from_id)

            choices = choices.values(
                'id', 'choice_text',
                'choice_type',
                'is_quotation_data',
                'is_packing_tips',
                'address_data_field_value',
                )
            return JsonResponse(list(choices), safe=False)

        return JsonResponse({})


class SaveCaseView(View):
    """sce bot quotation branch save case for ajax call"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(SaveCaseView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request):
        data = request.POST['data']
        case_data = json.loads(data)
        move_from_data = case_data.pop('move_from')
        move_to_data = case_data.pop('move_to')

        move_from_form = AddressForm(move_from_data)
        move_to_form = AddressForm(move_to_data)
        case_form = CaseForm(case_data)

        if move_from_form.is_valid() and move_to_form.is_valid() and case_form.is_valid():
            move_from = move_from_form.save()
            move_to = move_to_form.save()
            case = case_form.save(commit=False)
            case.move_from = move_from
            case.move_to = move_to
            case.save()
            return JsonResponse({"status": "ok", "case_id": case.id})
        else:
            return JsonResponse({
                "address_from": move_from_form.errors,
                "address_to": move_to_form.errors,
                "case_from": case_form.errors,
            })


class YoloObjectDetector:
    """yolo api handler"""
    url = settings.YOLO_URL

    def post(self, ci, hostname):
        try:
            response = requests.post(
                url=self.url,
                timeout=8,
                files={
                    'image': (ci.image.file.name, ci.image.file.file)
                })
        except:
            response = None
            msz = "Yolo api error for image "
            fr_email = settings.EMAIL_HOST_USER
            to_email = settings.EMAIL_HOST_USER
            helper.send_mail("Shalom: "+msz, msz+' : '+hostname+ci.image.url, fr_email, [to_email], fail_silently=True)

        if response is not None:
            try:
                data = json.loads(response.content)
            except:
                return []

            image_np = np.array(data.get('image', None))
            badges = data.get('badge', {})
            cv2.imwrite(ci.image.file.name, image_np)
            yolo_objects = list(badges.items())
            return yolo_objects

        return []


class UploadPhotosView(View):
    """sce bot room photo uploading"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(UploadPhotosView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request, **kwargs):
        case_id = request.POST.get('case_id', None)
        room_name = request.POST.get('room_name', '')
        room_id = kwargs.get('id', None)
        if room_id is None:
            case_room = CaseRoom.objects.create(case_id=case_id, room_name=room_name)
        else:
            case_room = CaseRoom.objects.get(id=room_id)
        initial_count = case_room.caseimage_set.count()


        for _file in request.FILES.getlist('file_input', []):
            case_image_form = CaseImageForm(request.POST, {"image": _file})

            if case_image_form.is_valid():
                case_image = case_image_form.save(commit=False)
                case_image.case_id = case_id
                case_image.caseroom = case_room
                case_image.save()

                yolo_objects = YoloObjectDetector().post(case_image, request.META['HTTP_HOST'])

                for yo in yolo_objects:
                    yo_objs = YoloObject.objects.filter(
                        obj=yo[0],
                        caseimage__case_id=case_id
                        )

                    if yo_objs.exists():
                        # will update qty only
                        # this way it leads to q condition 
                        # that one image has objects for all other image
                        yo_objs.update(qty=F('qty')+yo[1])
                    else:
                        YoloObject.objects.create(
                            caseimage=case_image,
                            obj=yo[0],
                            qty=yo[1],
                        )

            else:
                print(case_image_form.errors)
                return JsonResponse(case_image_form.errors)

        return JsonResponse({
            "status": "ok",
            "uploaded_files": case_room.caseimage_set.count()-initial_count,
            "room_id": case_room.id
            })


class RetryYoloView(View):
    """retry yolo api from case detail page"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(RetryYoloView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request, **kwargs):
        case_id = kwargs['id']
        case = get_object_or_404(Case, id=case_id)

        for case_image in case.caseimage_set.all():
            if not case_image.yoloobject_set.exists():
                yolo_objects = YoloObjectDetector().post(case_image, request.META['HTTP_HOST'])

                for yo in yolo_objects:
                    yo_objs = YoloObject.objects.filter(
                        obj=yo[0],
                        caseimage__case_id=case.id
                        )

                    if yo_objs.exists():
                        # will update qty only
                        # this way it leads to q condition 
                        # that one image has objects for all other image
                        yo_objs.update(qty=F('qty')+yo[1])
                    else:
                        YoloObject.objects.create(
                            caseimage=case_image,
                            obj=yo[0],
                            qty=yo[1],
                        )
        data = {
            "yos": [(yo.obj, yo.qty, yo.id) for yo in YoloObject.objects.filter(caseimage__case=case)]}
        return JsonResponse(data)


class BraineeAnswerView(View):
    """brainee api handler"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(BraineeAnswerView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request):
        brainee_input = request.POST.get('brainee_input', '')
        recipient_id = request.POST.get('recipient_id', f"shady123{random.randint(1,9)}")

        # data = {'brainee_input': brainee_input}
        # response = requests.post('http://192.168.1.41:9000/brainee/get-answer/', data).text
        data = {
            "project_id": "5cdd09872dd50300170e0790",
             "recipient_id": recipient_id,
             "message": brainee_input
         }
        response = requests.post(settings.BRAINEE_URL, json=data).text
        response = json.loads(response)
        return JsonResponse(response)


class BraineeQuestionEmailView(View):
    """mail view on brainee unable to find"""
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(BraineeQuestionEmailView, self).dispatch(request, *args, **kwargs)

    @staticmethod
    def post(request):
        # email shalom with 
        brainee_email = request.POST.get("braineeEmail", "")
        brainee_question = request.POST.get("braineeQuestion", "")

        # send email to shalom with above details in body
        subject = 'Query From SCE Bot'
        fr_email = settings.EMAIL_HOST_USER
        to_email = settings.EMAIL_HOST_USER
        msz = "Hi, please reply on this email id {}. Customer query is : {}".format(brainee_email, brainee_question)
        # send_mail(subject, msz, fr, [to], fail_silently=False)
        thread = threading.Thread(target=send_mail, args=(subject, msz, fr_email, [to_email], False))
        thread.start()
        return JsonResponse({"status": "ok"})


class MxBranchView(View):
    """m-x branch chat continue by token"""
    @staticmethod
    def get(request, **kwargs):
        case_id = urlsafe_base64_decode(kwargs.pop("caseidb64", None))
        token = kwargs.pop("token", None)
        case_token = get_object_or_404(CaseToken, case_id=case_id, token=token)
        case = case_token.case
        bot_id = Bot.objects.get(id=2)
        context = {"bot_id": bot_id}

        if case.move_ended:
            return redirect('chatbot:sce-bot')

        return render(request, 'chatbot/chatbot_mx_branch.html', context)

