import threading
import base64
from math import floor, ceil
from django.contrib.auth.models import User
from docxtpl import DocxTemplate
from django.conf import settings
from django.utils import timezone
from . import constants
from django.core.mail import send_mail as django_send_mail, EmailMultiAlternatives


def encrypt_email(email):
    # mohd.asif@infoxen.com => mohd.****@infoxen.com
    u, domain = email.split('@')
    u = u[:ceil(len(u) / 2)] + '*' * len(u[-floor(len(u) / 2):]) if len(u) > 1 else u
    return u + '@' + domain


def send_mail(subject, message, fr, to, fail_silently=True):
    # sending mail in thread
    thread = threading.Thread(target=django_send_mail, args=(subject, message, fr, to, fail_silently))
    t1 = thread.start()


def send_mail2(subject, text_content, html_content, from_email, to):
    # sending multialternative mail in thread
    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    thread = threading.Thread(target=msg.send)
    t1 = thread.start()


class Base64ToImageConverter:
    def __init__(self, imagestr, filename='image.png', with_details=True):
        self.imagestr = imagestr
        self.filename = filename
        if with_details:
            self.imagestr = imagestr.split(',')[1]

    def convert(self):
        imgdata = base64.b64decode(self.imagestr)
        
        with open(self.filename, 'wb') as f:
            f.write(imgdata)

        return self.filename


class YoloObjectDetector:

    url = settings.YOLO_URL

    def post(self, ci):
        try:
            response = requests.post(
                url=self.url,
                files={
                'image':(ci.image.file.name, ci.image.file.file)
                })
        except:
            response = None
            msz = "Yolo api error"
        if response is not None:
            data = json.loads(response.content)
            image_np = np.array(data.get('image', None))
            cv2.imwrite(ci.image.file.name, image_np)
            yolo_objects = data.get('objects', [])
            return yolo_objects

        return []


class AjaxSaveUser:
    def __init__(self, data):
        self.id = data.get('id', "") if data.get('id', "") != "" else None
        self.name = data.get('name', "")
        self.username = data.get('username', "")
        self.group_id = data.get('group_id', "")
        self.is_archive = data.get('is_archive', "")
        self.type = data.get('type', "")

    def save(self):
        if self.username != "":
            status = 'created'
            users = User.objects.filter(id=self.id)
            if users.exists():
                user = users.last()
                if User.objects.filter(username=self.username
                                       ).exclude(id=self.id).exists():
                    return {"status": "failed", "msz": "username already exists."}
                else:
                    user.username = self.username

                status = 'updated'
            else:
                user = User.objects.create(username=self.username)

            user.first_name = self.name.split(" ")[0]

            try:
                user.last_name = self.name.replace(user.first_name, "").strip()
            except IndexError:
                user.last_name = ""

            user.email = user.username
            user.is_active = True if self.is_archive == 'n' else False
            user.save()
            if self.group_id != "":
                user.groups.set([self.group_id])

            return {"status": status}

        raise NotImplementedError


class DynamicQuotation:
    def __init__(self, case):
        self.case = case

    def send_dynamic_quotation(self):
        case = self.case
        if not settings.SEND_DYNAMIC_QUOTATION:
            return

        output_file_path = f"/tmp/SCEbotQuoteDoc{case.id}.docx"
        doc = DocxTemplate(settings.BASE_DIR + "/docs/SCEbotQuoteDoc.docx")
        SAMPLE_INSURANCE_FORM_GENERAL_CARGO = settings.BASE_DIR + "/docs/A. SAMPLE INSURANCE FORM - GENERAL CARGO.pdf"
        INSURANCE_FORM_MUSICAL_INSTRUMENTS = settings.BASE_DIR + "/docs/A. INSURANCE FORM - MUSICAL INSTRUMENTS.pdf"
        INSURANCE_FORM_GENERAL_CARGO = settings.BASE_DIR + "/docs/A. INSURANCE FORM - GENERAL CARGO.pdf"

        context = {"case": case, 'dt': timezone.now()}
        doc.render(context)
        doc.save(output_file_path)
        msg = EmailMultiAlternatives(
            constants.DYNAMIC_QUOTATION_SUBJECT,
            constants.DYNAMIC_QUOTATION_BODY_TEXT.format(case.customer_name.title()),
            settings.EMAIL_HOST_USER, ['mohd.asif@infoxen.com'])
        msg.attach_alternative(constants.DYNAMIC_QUOTATION_BODY_HTML.format(case.customer_name.title()), "text/html")
        msg.attach_file(output_file_path, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        # attach pdf files
        msg.attach_file(SAMPLE_INSURANCE_FORM_GENERAL_CARGO, 'application/pdf')
        msg.attach_file(INSURANCE_FORM_MUSICAL_INSTRUMENTS, 'application/pdf')
        msg.attach_file(INSURANCE_FORM_GENERAL_CARGO, 'application/pdf')
        msg.attach_file(SHALOM_MOVERS_LIST_OF_CUSTOMER, 'application/pdf')
        try:
            msg.send()
        except Exception as e:
            print(e)

    def send_mail(self):
        t = threading.Thread(target=self.send_dynamic_quotation)
        t.start()

