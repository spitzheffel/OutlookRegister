import random
import string
import secrets

# 常见英文名
FIRST_NAMES = [
    'james', 'john', 'robert', 'michael', 'david', 'william', 'richard', 'joseph', 'thomas', 'charles',
    'mary', 'patricia', 'jennifer', 'linda', 'elizabeth', 'barbara', 'susan', 'jessica', 'sarah', 'karen',
    'daniel', 'matthew', 'anthony', 'mark', 'donald', 'steven', 'paul', 'andrew', 'joshua', 'kenneth',
    'emily', 'emma', 'olivia', 'sophia', 'isabella', 'mia', 'charlotte', 'amelia', 'harper', 'evelyn',
    'alex', 'ryan', 'kevin', 'brian', 'george', 'edward', 'henry', 'jason', 'adam', 'nathan',
    'grace', 'lily', 'chloe', 'hannah', 'ella', 'madison', 'aria', 'luna', 'victoria', 'stella'
]

LAST_NAMES = [
    'smith', 'johnson', 'williams', 'brown', 'jones', 'garcia', 'miller', 'davis', 'rodriguez', 'martinez',
    'wilson', 'anderson', 'taylor', 'thomas', 'moore', 'jackson', 'martin', 'lee', 'thompson', 'white',
    'harris', 'clark', 'lewis', 'walker', 'hall', 'allen', 'young', 'king', 'wright', 'hill',
    'scott', 'green', 'baker', 'adams', 'nelson', 'carter', 'mitchell', 'roberts', 'turner', 'phillips'
]

def random_email():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    digits = ''.join(random.choices(string.digits, k=6))
    email = f"{first}{last}{digits}"
    return email, first.capitalize(), last.capitalize()

def generate_strong_password(length=random.randint(11, 15)):

    chars = string.ascii_letters + string.digits + "!@#$%^&*"

    while True:
        password = ''.join(secrets.choice(chars) for _ in range(length))

        if (any(c.islower() for c in password) 
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in "!@#$%^&*" for c in password)):
            return password
