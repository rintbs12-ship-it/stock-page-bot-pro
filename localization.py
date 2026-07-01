import re

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


PHRASES = {
    "Something went wrong. Please try again from /start.": "មានបញ្ហាមួយបានកើតឡើង។ សូមសាកល្បងម្តងទៀតតាម /start។",
    "Admin only": "សម្រាប់ Admin ប៉ុណ្ណោះ",
    "Stock not found.": "រកមិនឃើញស្តុក។",
    "Order not found.": "រកមិនឃើញការកម្មង់។",
    "No stock available.": "មិនមានស្តុកទេ។",
    "Please contact admin.": "សូមទាក់ទង Admin។",
    "Please send a valid": "សូមផ្ញើតម្លៃដែលត្រឹមត្រូវ",
    "Please choose": "សូមជ្រើសរើស",
    "Please send": "សូមផ្ញើ",
    "Please upload": "សូមផ្ញើ",
    "Please wait": "សូមរង់ចាំ",
    "Information saved.": "ព័ត៌មានត្រូវបានរក្សាទុករួចរាល់។",
    "Admin is processing your order.": "Admin កំពុងដំណើរការកម្មង់របស់អ្នក។",
    "Admin has been added to the page.": "Admin ត្រូវបានបន្ថែមចូលក្នុង Page របស់អ្នករួចហើយ។",
    "Please open Facebook and accept the page invite.": "សូមបើក Facebook ហើយទទួលយកការអញ្ជើញ (Page Invite)។",
    "Payment approved": "ការទូទាត់ត្រូវបានអនុម័ត",
    "Payment rejected": "ការទូទាត់ត្រូវបានបដិសេធ",
    "Receipt uploaded": "បង្កាន់ដៃត្រូវបានផ្ញើរួច",
    "Upload Receipt": "ផ្ញើបង្កាន់ដៃ",
    "Share on Telegram": "ចែករំលែកតាម Telegram",
    "Add Stock Wizard": "ដំណាក់កាលបន្ថែមស្តុក",
    "Ready to Transfer": "ត្រៀមផ្ទេរសិទ្ធិ",
    "Business Ready": "ត្រៀមសម្រាប់អាជីវកម្ម",
    "No Policy Violation": "គ្មានការរំលោភគោលការណ៍",
    "Real Followers": "អ្នកតាមដានពិត",
    "Organic Reach": "ការមើលឃើញធម្មជាតិ",
    "Female percent": "ភាគរយស្ត្រី",
    "Male percent": "ភាគរយបុរស",
    "Quality percent": "ភាគរយគុណភាព",
    "Page Type": "ប្រភេទ Page",
    "Facebook Page Link": "តំណ Facebook Page",
    "Manage Stock": "គ្រប់គ្រងស្តុក",
    "Add Stock": "បន្ថែមស្តុក",
    "Edit Stock": "កែប្រែស្តុក",
    "Quick Edit": "កែប្រែរហ័ស",
    "Toggle Promotion": "បើក/បិទប្រូម៉ូសិន",
    "Toggle Featured": "បើក/បិទស្តុកពិសេស",
    "Mark Available": "ដាក់ថាមានលក់",
    "Mark Sold": "ដាក់ថាលក់រួច",
    "Upload Photos": "ផ្ញើរូបភាព",
    "View Photos": "មើលរូបភាព",
    "Delete One Photo": "លុបរូបភាពមួយ",
    "Delete Multiple Photos": "លុបរូបភាពច្រើន",
    "Delete All Photos": "លុបរូបភាពទាំងអស់",
    "Photo Manager": "គ្រប់គ្រងរូបភាព",
    "Order Manager": "គ្រប់គ្រងការកម្មង់",
    "Notification Center": "មជ្ឈមណ្ឌលជូនដំណឹង",
    "Reminder Manager": "គ្រប់គ្រងការរំលឹក",
    "Backup Manager": "គ្រប់គ្រងការបម្រុងទុក",
    "Analytics Dashboard": "ផ្ទាំងវិភាគទិន្នន័យ",
    "Customer Analytics": "ការវិភាគអតិថិជន",
    "Advanced Search": "ស្វែងរកកម្រិតខ្ពស់",
    "Scheduled Announcements": "សេចក្តីប្រកាសដែលបានកំណត់ពេល",
    "Audit Logs": "កំណត់ត្រាសកម្មភាព",
    "Main Menu": "ម៉ឺនុយដើម",
    "Admin Panel": "ផ្ទាំង Admin",
}

WORDS = {
    "Back": "ត្រឡប់ក្រោយ", "Cancel": "បោះបង់", "Yes": "បាទ",
    "No": "ទេ", "Delete": "លុប", "Edit": "កែប្រែ",
    "Save": "រក្សាទុក", "Saved": "បានរក្សាទុក", "Search": "ស្វែងរក",
    "Settings": "ការកំណត់", "Language": "ភាសា", "Help": "ជំនួយ",
    "Customer": "អតិថិជន", "Customers": "អតិថិជន",
    "Order": "ការកម្មង់", "Orders": "ការកម្មង់",
    "Payment": "ការទូទាត់", "Receipt": "បង្កាន់ដៃ",
    "Stock": "ស្តុក", "Photos": "រូបភាព", "Photo": "រូបភាព",
    "Followers": "អ្នកតាមដាន", "Price": "តម្លៃ", "Country": "ប្រទេស",
    "Audience": "អ្នកទស្សនា", "Quality": "គុណភាព", "Status": "ស្ថានភាព",
    "Available": "មានលក់", "Sold": "លក់រួច", "Featured": "ស្តុកពិសេស",
    "Promotion": "ប្រូម៉ូសិន", "Statistics": "ស្ថិតិ",
    "Analytics": "ការវិភាគ", "Notifications": "ការជូនដំណឹង",
    "Announcement": "សេចក្តីប្រកាស", "Announcements": "សេចក្តីប្រកាស",
    "Scheduler": "កម្មវិធីកំណត់ពេល", "Maintenance": "ការថែទាំ",
    "Refresh": "ផ្ទុកឡើងវិញ", "Export": "នាំចេញ", "Import": "នាំចូល",
    "Previous": "មុន", "Next": "បន្ទាប់", "Done": "រួចរាល់",
    "Confirm": "បញ្ជាក់", "Approved": "បានអនុម័ត", "Rejected": "បានបដិសេធ",
    "Completed": "បានបញ្ចប់", "Cancelled": "បានបោះបង់",
    "Waiting": "កំពុងរង់ចាំ", "Processing": "កំពុងដំណើរការ",
    "Invalid": "មិនត្រឹមត្រូវ", "Error": "កំហុស",
    "Success": "ជោគជ័យ", "Failed": "បរាជ័យ",
    "Name": "ឈ្មោះ", "Username": "ឈ្មោះអ្នកប្រើ", "Phone": "លេខទូរស័ព្ទ",
    "Today": "ថ្ងៃនេះ", "Daily": "រាល់ថ្ងៃ", "Weekly": "រាល់សប្ដាហ៍",
    "Monthly": "រាល់ខែ", "History": "ប្រវត្តិ", "Details": "ព័ត៌មានលម្អិត",
    "Profile": "ប្រវត្តិរូប", "Menu": "ម៉ឺនុយ", "Theme": "រចនាប័ទ្ម",
    "Description": "ការពិពណ៌នា", "Amount": "ចំនួនទឹកប្រាក់",
    "Total": "សរុប", "Active": "កំពុងដំណើរការ",
    "Movie": "ភាពយន្ត", "Gaming": "ហ្គេម", "Shopping": "ការទិញទំនិញ",
    "Beauty": "សម្រស់", "Technology": "បច្ចេកវិទ្យា", "Food": "អាហារ",
    "Sports": "កីឡា", "News": "ព័ត៌មាន", "Music": "តន្ត្រី",
    "Entertainment": "កម្សាន្ត", "Education": "ការអប់រំ", "Travel": "ដំណើរកម្សាន្ត",
    "Automotive": "យានយន្ត", "Pets": "សត្វចិញ្ចឹម",
    "Business": "អាជីវកម្ម", "Finance": "ហិរញ្ញវត្ថុ",
    "Books": "សៀវភៅ", "Art": "សិល្បៈ", "Photography": "ការថតរូប",
    "Health": "សុខភាព", "Fitness": "ហាត់ប្រាណ", "Kids": "កុមារ",
    "Fashion": "ម៉ូដ", "Male": "បុរស", "Female": "ស្ត្រី",
    "Equal": "ស្មើគ្នា", "High": "ខ្ពស់", "Medium": "មធ្យម", "Low": "ទាប",
    "All": "ទាំងអស់", "Selected": "បានជ្រើស", "Select": "ជ្រើសរើស",
    "Create": "បង្កើត", "Update": "ធ្វើបច្ចុប្បន្នភាព", "Remove": "ដកចេញ",
    "Open": "បើក", "Copy": "ចម្លង", "Link": "តំណ", "Contact": "ទាក់ទង",
    "Buy": "ទិញ", "Now": "ឥឡូវនេះ", "Favorite": "ចំណូលចិត្ត",
    "Share": "ចែករំលែក", "Upload": "ផ្ញើឡើង", "Download": "ទាញយក",
    "Enable": "បើក", "Enabled": "បានបើក", "Disable": "បិទ",
    "Disabled": "បានបិទ", "Reason": "មូលហេតុ", "Report": "របាយការណ៍",
    "Date": "កាលបរិច្ឆេទ", "Time": "ពេលវេលា", "Action": "សកម្មភាព",
    "Target": "គោលដៅ", "Result": "លទ្ធផល", "Results": "លទ្ធផល",
    "New": "ថ្មី", "Recent": "ថ្មីៗ", "Value": "តម្លៃ",
    "English": "អង់គ្លេស", "Khmer": "ខ្មែរ", "Website": "គេហទំព័រ",
    "Chat": "ជជែក", "Message": "សារ", "Broadcast": "ការផ្សាយសារ",
}


def translate_ui_text(value):
    if not isinstance(value, str) or not re.search(r"[A-Za-z]", value):
        return value
    translated = value
    for source in sorted(PHRASES, key=len, reverse=True):
        translated = translated.replace(source, PHRASES[source])
    for source, target in WORDS.items():
        translated = re.sub(
            rf"\b{re.escape(source)}\b", target, translated,
            flags=re.IGNORECASE,
        )
    return translated


def translate_reply_markup(markup):
    if isinstance(markup, InlineKeyboardMarkup):
        rows = []
        for row in markup.inline_keyboard:
            translated_row = []
            for button in row:
                data = button.to_dict()
                data["text"] = translate_ui_text(data["text"])
                translated_row.append(InlineKeyboardButton.de_json(data, None))
            rows.append(translated_row)
        return InlineKeyboardMarkup(rows)
    if isinstance(markup, ReplyKeyboardMarkup):
        rows = []
        for row in markup.keyboard:
            translated_row = []
            for button in row:
                data = button.to_dict()
                data["text"] = translate_ui_text(data["text"])
                translated_row.append(KeyboardButton.de_json(data, None))
            rows.append(translated_row)
        return ReplyKeyboardMarkup(
            rows,
            resize_keyboard=markup.resize_keyboard,
            one_time_keyboard=markup.one_time_keyboard,
            selective=markup.selective,
            input_field_placeholder=translate_ui_text(
                markup.input_field_placeholder
            ),
            is_persistent=markup.is_persistent,
        )
    return markup
