import os
import random
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "healthshield_2026_prod")

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///healthshield_local.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    __tablename__ = 'users'
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80), unique=True, nullable=False)
    password     = db.Column(db.String(120), nullable=False)
    role         = db.Column(db.String(20), nullable=False)
    name         = db.Column(db.String(120), nullable=False)
    notifications = db.relationship('Notification', backref='user', lazy=True)

class Policy(db.Model):
    __tablename__ = 'policies'
    id            = db.Column(db.Integer, primary_key=True)
    number        = db.Column(db.String(20), unique=True, nullable=False)
    holder_name   = db.Column(db.String(120), nullable=False)
    plan          = db.Column(db.String(80), default='Standard Comprehensive')
    limit_amount  = db.Column(db.Integer, default=500000)
    remaining     = db.Column(db.Integer, default=500000)
    status        = db.Column(db.String(20), default='Active')
    expiry        = db.Column(db.String(20), default='2027-12-31')
    covered       = db.Column(db.Text, default='Surgery,Chemotherapy,Dialysis,Asthma,Cardiac,Orthopedic Surgery')

    def get_covered(self):
        return [c.strip() for c in self.covered.split(',')]

    def to_dict(self):
        return {
            'number':    self.number,
            'holder':    self.holder_name,
            'plan':      self.plan,
            'limit':     self.limit_amount,
            'remaining': self.remaining,
            'status':    self.status,
            'expiry':    self.expiry,
            'covered':   self.get_covered()
        }

class Claim(db.Model):
    __tablename__ = 'claims'
    id           = db.Column(db.String(20), primary_key=True)
    patient      = db.Column(db.String(120), nullable=False)
    hospital     = db.Column(db.String(120), nullable=False)
    date         = db.Column(db.String(20), nullable=False)
    amount       = db.Column(db.Integer, nullable=False)
    status       = db.Column(db.String(30), default='Submitted')
    risk         = db.Column(db.String(10), default='Low')
    score        = db.Column(db.Integer, default=0)
    treatment    = db.Column(db.String(100), nullable=False)
    policy_no    = db.Column(db.String(20), nullable=False)
    officer_note = db.Column(db.Text, default='')

    def to_dict(self):
        return {
            'id':           self.id,
            'patient':      self.patient,
            'hospital':     self.hospital,
            'date':         self.date,
            'amount':       self.amount,
            'status':       self.status,
            'risk':         self.risk,
            'score':        self.score,
            'treatment':    self.treatment,
            'policy':       self.policy_no,
            'officer_note': self.officer_note
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id        = db.Column(db.Integer, primary_key=True)
    time      = db.Column(db.String(30), nullable=False)
    user      = db.Column(db.String(120), nullable=False)
    action    = db.Column(db.Text, nullable=False)
    claim_ref = db.Column(db.String(20), default='N/A')

    def to_dict(self):
        return {
            'time':   self.time,
            'user':   self.user,
            'action': self.action,
            'claim':  self.claim_ref
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    msg     = db.Column(db.Text, nullable=False)
    read    = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {'msg': self.msg, 'read': self.read}

FRAUD_RULES = [
    {"id": "FR-01", "name": "High Claim Amount (>150% benchmark)",    "weight": 25},
    {"id": "FR-02", "name": "Claim Frequency (>2 claims in 30 days)", "weight": 20},
    {"id": "FR-03", "name": "Coverage Mismatch",                      "weight": 20},
    {"id": "FR-04", "name": "Hospital Activity Anomaly",              "weight": 15},
    {"id": "FR-05", "name": "Incomplete Documentation",               "weight": 10},
    {"id": "FR-06", "name": "Late Submission (>90 days)",             "weight": 5},
    {"id": "FR-07", "name": "Policy Impending Expiry (<30 days)",      "weight": 3}
]

with app.app_context():
    db.create_all()

@app.context_processor
def inject_alerts():
    if 'user_id' in session:
        unread = Notification.query.filter_by(user_id=session['user_id'], read=False).count()
        return dict(unread=unread)
    return dict(unread=0)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        role     = request.form.get('role', '')
        name     = request.form.get('name', '').strip()

        if not all([username, password, role, name]):
            flash("All registration fields are mandatory.")
            return redirect(url_for('signup'))

        if User.query.filter_by(username=username).first():
            flash("Username already exists! Please choose another.")
            return redirect(url_for('signup'))

        user = User(username=username, password=password, role=role, name=name)
        db.session.add(user)
        db.session.flush()

        if role == 'policyholder':
            p_num  = f"POL-{random.randint(10000, 99999)}"
            policy = Policy(number=p_num, holder_name=name)
            db.session.add(policy)
            notif = Notification(
                user_id=user.id,
                msg=f"Welcome! Policy {p_num} provisioned with PKR 500,000 coverage."
            )
            db.session.add(notif)

        db.session.commit()
        flash("Registration successful! Log in below.")
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(username=username, password=password).first()

        if user:
            session['user_id'] = user.id
            session['user']    = user.username
            session['role']    = user.role
            session['name']    = user.name

            log = AuditLog(
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user=user.name,
                action="Authenticated successfully into the portal"
            )
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials. Please try again.")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session['role']
    name = session['name']

    if role == 'hospital':
        claims_db = Claim.query.filter_by(hospital=name).all()
        claims    = [c.to_dict() for c in claims_db]
        stats = {
            "total":    len(claims),
            "pending":  sum(1 for c in claims if c['status'] in ['Submitted','Under Review','Escalated']),
            "approved": sum(1 for c in claims if c['status'] == 'Approved'),
            "rejected": sum(1 for c in claims if c['status'] == 'Rejected')
        }
        return render_template('dashboard.html', role=role, claims=claims, stats=stats)

    elif role in ['officer', 'admin']:
        claims_db = Claim.query.all()
        claims    = [c.to_dict() for c in claims_db]
        stats = {
            "pending":   sum(1 for c in claims if c['status'] in ['Submitted','Under Review','Escalated','Info Requested']),
            "high_risk": sum(1 for c in claims if c['risk'] == 'High'),
            "approved":  sum(1 for c in claims if c['status'] == 'Approved'),
            "rejected":  sum(1 for c in claims if c['status'] == 'Rejected')
        }
        return render_template('dashboard.html', role=role, claims=claims, stats=stats)

    elif role == 'policyholder':
        claims_db = Claim.query.filter_by(patient=name).all()
        claims    = [c.to_dict() for c in claims_db]
        stats = {
            "total":    len(claims),
            "approved": sum(1 for c in claims if c['status'] == 'Approved'),
            "pending":  sum(1 for c in claims if c['status'] not in ['Approved','Rejected'])
        }
        return render_template('dashboard.html', role=role, claims=claims, stats=stats)

@app.route('/submit-claim', methods=['GET', 'POST'])
def submit_claim():
    if session.get('role') != 'hospital':
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        p_no      = request.form.get('policy_no', '').strip()
        patient   = request.form.get('patient', '').strip()
        treatment = request.form.get('treatment', '')
        amount    = int(request.form.get('amount', 0))

        score  = random.randint(10, 45)
        policy = Policy.query.filter_by(number=p_no).first()

        if not policy:
            score += 35
        elif treatment not in policy.get_covered():
            score += 25

        if amount > 250000:
            score += 20

        score  = min(score, 100)
        risk   = "High" if score >= 70 else "Medium" if score >= 35 else "Low"
        status = "Escalated" if risk == "High" else "Submitted"
        c_id   = f"CLM-{random.randint(100000, 999999)}"

        claim = Claim(
            id=c_id, patient=patient, hospital=session['name'],
            date=datetime.now().strftime("%Y-%m-%d"), amount=amount,
            status=status, risk=risk, score=score,
            treatment=treatment, policy_no=p_no
        )
        db.session.add(claim)

        matched_user = User.query.filter_by(role='policyholder', name=patient).first()
        if matched_user:
            notif = Notification(
                user_id=matched_user.id,
                msg=f"New claim {c_id} submitted for you by {session['name']}."
            )
            db.session.add(notif)

        log = AuditLog(
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user=session['name'], action="Submitted new claim", claim_ref=c_id
        )
        db.session.add(log)
        db.session.commit()

        flash(f"Claim submitted successfully. Reference: {c_id}")
        return redirect(url_for('dashboard'))

    return render_template('submit_claim.html')

@app.route('/review-queue')
def review_queue():
    if session.get('role') not in ['officer', 'admin']:
        return redirect(url_for('dashboard'))

    active = Claim.query.filter(
        Claim.status.in_(['Submitted','Under Review','Escalated','Info Requested'])
    ).order_by(Claim.score.desc()).all()

    return render_template('review_queue.html', claims=[c.to_dict() for c in active])

@app.route('/review/<claim_id>', methods=['GET', 'POST'])
def review_claim(claim_id):
    if session.get('role') not in ['officer', 'admin']:
        return redirect(url_for('dashboard'))

    claim = Claim.query.get(claim_id)
    if not claim:
        return redirect(url_for('review_queue'))

    if claim.status == 'Submitted':
        claim.status = 'Under Review'
        db.session.commit()

    policy = Policy.query.filter_by(number=claim.policy_no).first()
    policy_dict = policy.to_dict() if policy else None

    if request.method == 'POST':
        action = request.form.get('action')
        note   = request.form.get('note', '').strip()
        claim.officer_note = note

        if action == 'approve':
            claim.status = 'Approved'
            if policy:
                policy.remaining = max(0, policy.remaining - claim.amount)
        elif action == 'reject':
            claim.status = 'Rejected'
        elif action == 'info':
            claim.status = 'Info Requested'

        for role_name in ['policyholder', 'hospital']:
            target_name = claim.patient if role_name == 'policyholder' else claim.hospital
            target_user = User.query.filter_by(role=role_name, name=target_name).first()
            if target_user:
                notif = Notification(
                    user_id=target_user.id,
                    msg=f"Claim {claim_id} updated to [{claim.status}]. Reason: {note}"
                )
                db.session.add(notif)

        log = AuditLog(
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user=session['name'],
            action=f"Status changed to: {claim.status}",
            claim_ref=claim_id
        )
        db.session.add(log)
        db.session.commit()

        flash(f"Claim {claim_id} updated successfully.")
        return redirect(url_for('review_queue'))

    return render_template('review_claim.html', claim=claim.to_dict(), policy=policy_dict, rules=FRAUD_RULES)

@app.route('/track-claims')
def track_claims():
    if session.get('role') != 'policyholder':
        return redirect(url_for('dashboard'))

    claims   = [c.to_dict() for c in Claim.query.filter_by(patient=session['name']).all()]
    policy   = Policy.query.filter_by(holder_name=session['name']).first()
    pol_dict = policy.to_dict() if policy else None

    return render_template('track_claims.html', claims=claims, policy=pol_dict)

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    notifs = Notification.query.filter_by(user_id=session['user_id']).all()
    for n in notifs:
        n.read = True
    db.session.commit()

    return render_template('notifications.html', notifications=[n.to_dict() for n in notifs])

@app.route('/audit-log')
def audit_log():
    if session.get('role') not in ['officer', 'admin']:
        return redirect(url_for('dashboard'))

    logs = AuditLog.query.order_by(AuditLog.id.desc()).all()
    return render_template('audit_log.html', logs=[l.to_dict() for l in logs])

@app.route('/reports')
def reports():
    if session.get('role') not in ['officer', 'admin']:
        return redirect(url_for('dashboard'))

    all_claims = [c.to_dict() for c in Claim.query.all()]
    stats = {
        "total":     len(all_claims),
        "approved":  sum(1 for c in all_claims if c['status'] == 'Approved'),
        "rejected":  sum(1 for c in all_claims if c['status'] == 'Rejected'),
        "high_risk": sum(1 for c in all_claims if c['risk'] == 'High'),
        "medium":    sum(1 for c in all_claims if c['risk'] == 'Medium'),
        "low":       sum(1 for c in all_claims if c['risk'] == 'Low')
    }
    return render_template('reports.html', stats=stats, claims=all_claims, rules=FRAUD_RULES)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
