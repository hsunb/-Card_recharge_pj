from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

db_host = os.environ.get('DB_HOST')
db_port = os.environ.get('DB_PORT', '3306')
db_pass = os.environ.get('MARIADB_ROOT_PASSWORD')
if db_host and db_pass:
    import pymysql
    conn = pymysql.connect(unix_socket='/var/run/mysqld/mysqld.sock', user='root', password=db_pass)
    conn.cursor().execute('CREATE DATABASE IF NOT EXISTS card_recharge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    conn.close()
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://root:{db_pass}@localhost/card_recharge?unix_socket=/var/run/mysqld/mysqld.sock'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///card_recharge.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'seonbinnam@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', 'seonbinnam@gmail.com')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요합니다.'
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    depositor_name = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    requests = db.relationship('ChargeRequest', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ChargeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    deposit_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='대기중')
    reject_reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        depositor_name = request.form.get('depositor_name', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if not student_id.isdigit() or len(student_id) != 8:
            flash('학번은 8자리 숫자여야 합니다.')
            return render_template('register.html')
        if password != password2:
            flash('비밀번호가 일치하지 않습니다.')
            return render_template('register.html')
        if User.query.filter_by(student_id=student_id).first():
            flash('이미 등록된 학번입니다.')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('이미 등록된 이메일입니다.')
            return render_template('register.html')

        user = User(student_id=student_id, name=name, email=email, depositor_name=depositor_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('회원가입이 완료되었습니다. 로그인해주세요.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(student_id=student_id).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin_dashboard' if user.is_admin else 'dashboard'))
        flash('학번 또는 비밀번호가 올바르지 않습니다.')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    requests = ChargeRequest.query.filter_by(user_id=current_user.id).order_by(ChargeRequest.created_at.desc()).all()
    return render_template('dashboard.html', requests=requests)


@app.route('/mypage', methods=['GET', 'POST'])
@login_required
def mypage():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        depositor_name = request.form.get('depositor_name', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        new_password2 = request.form.get('new_password2', '')

        if not current_user.check_password(current_password):
            flash('현재 비밀번호가 올바르지 않습니다.')
            return render_template('mypage.html')

        if email != current_user.email:
            if User.query.filter_by(email=email).first():
                flash('이미 사용 중인 이메일입니다.')
                return render_template('mypage.html')

        current_user.name = name
        current_user.email = email
        current_user.depositor_name = depositor_name

        if new_password:
            if new_password != new_password2:
                flash('새 비밀번호가 일치하지 않습니다.')
                return render_template('mypage.html')
            current_user.set_password(new_password)

        db.session.commit()
        flash('정보가 수정되었습니다.')
        return redirect(url_for('mypage'))
    return render_template('mypage.html')


@app.route('/request/new', methods=['GET', 'POST'])
@login_required
def new_request():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        deposit_date = request.form.get('deposit_date', '').strip()

        if not amount.isdigit() or int(amount) < 1000:
            flash('충전 금액은 1,000원 이상이어야 합니다.')
            return render_template('new_request.html')

        pending = ChargeRequest.query.filter_by(user_id=current_user.id, status='대기중').first()
        if pending:
            flash('이미 처리 대기 중인 요청이 있습니다. 처리 완료 후 새 요청을 등록해주세요.')
            return render_template('new_request.html')

        try:
            deposit_date_obj = datetime.strptime(deposit_date, '%Y-%m-%d').date()
        except ValueError:
            flash('날짜 형식이 올바르지 않습니다.')
            return render_template('new_request.html')

        charge_request = ChargeRequest(
            user_id=current_user.id,
            amount=int(amount),
            deposit_date=deposit_date_obj
        )
        db.session.add(charge_request)
        db.session.commit()
        flash('충전 요청이 등록되었습니다.')
        return redirect(url_for('dashboard'))
    return render_template('new_request.html')


@app.route('/request/<int:request_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_request(request_id):
    charge_request = ChargeRequest.query.get_or_404(request_id)
    if charge_request.user_id != current_user.id:
        flash('권한이 없습니다.')
        return redirect(url_for('dashboard'))
    if charge_request.status != '대기중':
        flash('대기 중인 요청만 수정할 수 있습니다.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        deposit_date = request.form.get('deposit_date', '').strip()

        if not amount.isdigit() or int(amount) < 1000:
            flash('충전 금액은 1,000원 이상이어야 합니다.')
            return render_template('edit_request.html', req=charge_request)
        try:
            deposit_date_obj = datetime.strptime(deposit_date, '%Y-%m-%d').date()
        except ValueError:
            flash('날짜 형식이 올바르지 않습니다.')
            return render_template('edit_request.html', req=charge_request)

        charge_request.amount = int(amount)
        charge_request.deposit_date = deposit_date_obj
        charge_request.updated_at = datetime.utcnow()
        db.session.commit()
        flash('요청이 수정되었습니다.')
        return redirect(url_for('dashboard'))
    return render_template('edit_request.html', req=charge_request)


@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    pending = ChargeRequest.query.filter_by(status='대기중').order_by(ChargeRequest.created_at.asc()).all()
    completed = ChargeRequest.query.filter(ChargeRequest.status != '대기중').order_by(ChargeRequest.updated_at.desc()).limit(20).all()
    users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).all()
    return render_template('admin_dashboard.html', pending=pending, completed=completed, users=users)


@app.route('/admin/request/<int:request_id>/complete', methods=['POST'])
@login_required
def complete_request(request_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    charge_request = ChargeRequest.query.get_or_404(request_id)
    charge_request.status = '처리완료'
    charge_request.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f'{charge_request.user.name} 학생의 충전 요청이 처리완료 되었습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/request/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_request(request_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    charge_request = ChargeRequest.query.get_or_404(request_id)
    reason = request.form.get('reason', '').strip()
    charge_request.status = '거절'
    charge_request.reject_reason = reason
    charge_request.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f'{charge_request.user.name} 학생의 충전 요청이 거절되었습니다.')
    return redirect(url_for('admin_dashboard'))


@app.route('/delete-account')
@login_required
def delete_account():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    user = User.query.get(current_user.id)
    ChargeRequest.query.filter_by(user_id=user.id).delete()
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash('회원 탈퇴가 완료되었습니다.')
    return redirect(url_for('index'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            token = serializer.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            try:
                msg = Message('비밀번호 재설정', recipients=[email])
                msg.body = f'아래 링크를 클릭하여 비밀번호를 재설정하세요. (1시간 유효)\n\n{reset_url}'
                mail.send(msg)
            except Exception:
                pass
        flash('이메일이 등록되어 있다면 재설정 링크를 발송했습니다.')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except (SignatureExpired, BadSignature):
        flash('링크가 만료되었거나 유효하지 않습니다.')
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('사용자를 찾을 수 없습니다.')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        new_password2 = request.form.get('new_password2', '')
        if new_password != new_password2:
            flash('비밀번호가 일치하지 않습니다.')
            return render_template('reset_password.html')
        user.set_password(new_password)
        db.session.commit()
        flash('비밀번호가 재설정되었습니다. 로그인해주세요.')
        return redirect(url_for('login'))
    return render_template('reset_password.html')


with app.app_context():
    db.create_all()
    if not User.query.filter_by(student_id='00000000').first():
        admin = User(student_id='00000000', name='관리자', email='admin@suwon.ac.kr', depositor_name='관리자', is_admin=True)
        admin.set_password('admin1234')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
