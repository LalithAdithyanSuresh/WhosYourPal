from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory,jsonify
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import pymysql
from functools import wraps
import os
from dotenv import load_dotenv



load_dotenv() 


app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a_default_secret_key_if_env_missing') 
if app.secret_key == 'a_default_secret_key_if_env_missing':
    print("WARNING: SECRET_KEY not found in .env file. Using default (unsafe).")
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = 'info'

class User(UserMixin):
    def __init__(self, id, username, email, is_admin, shelter_id=None, shelter_name=None):
        self.id = id
        self.username = username
        self.email = email
        self.is_admin = bool(is_admin)
        self.shelter_id = shelter_id
        self.shelter_name = shelter_name

    @property
    def admin(self):
        return self.is_admin

timeout = 10 
db_port_str = os.getenv('DB_PORT') 

connection_params = {
    "charset": os.getenv('DB_CHARSET', 'utf8mb4'), 
    "connect_timeout": timeout,
    "cursorclass": pymysql.cursors.DictCursor,
    "db": os.getenv('DB_NAME'),
    "host": os.getenv('DB_HOST'),
    "password": os.getenv('DB_PASSWORD'),
    "user": os.getenv('DB_USER'),
    "read_timeout": timeout,
    "write_timeout": timeout,
    "port": int(db_port_str) if db_port_str and db_port_str.isdigit() else 23243 
}

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

@login_manager.user_loader
def load_user(user_id):
    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """
                SELECT
                    u.id, u.username, u.email, u.admin,
                    s.SHELTER_ID, s.NAME as SHELTER_NAME
                FROM users u
                LEFT JOIN SHELTERS s ON u.SHELTER_ID = s.SHELTER_ID
                WHERE u.id = %s
            """
            cursor.execute(sql, (user_id,))
            user_data = cursor.fetchone()

            if user_data:
                is_admin_flag = user_data.get('admin', 0)
                shelter_id_val = user_data.get('SHELTER_ID') if is_admin_flag == 1 else None
                shelter_name_val = user_data.get('SHELTER_NAME') if is_admin_flag == 1 and shelter_id_val else None

                return User(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    is_admin=is_admin_flag,
                    shelter_id=shelter_id_val,
                    shelter_name=shelter_name_val
                )
    except pymysql.MySQLError as e:
        print(f"Error loading user {user_id}: {e}")
    finally:
        if connection and connection.open:
            connection.close()
    return None

# === Authorization Decorator ===
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
             flash("Please log in to access this page.", "warning")
             return redirect(url_for('login', next=request.url))

        if not getattr(current_user, 'is_admin', False):
            flash("You do not have permission to access the admin area.", "danger")
            return redirect(url_for('dashboard'))

        if not getattr(current_user, 'shelter_id', None):
             flash("Admin account requires an associated shelter.", "danger")
             logout_user()
             return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/icon/<path:path>")
def icon(path):
    return send_from_directory("assets/icons", path)
@app.route("/admin/icon/<path:path>")
def aicon(path):
    return send_from_directory("assets/icons", path)
@app.route("/pet/icon/<path:path>")
def picon(path):
    return send_from_directory("assets/icons", path)
@app.route("/shelter/icon/<path:path>")
def sicon(path):
    return send_from_directory("assets/icons", path)
# === USER Routes ===
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if not all([username, email, password]):
            flash("All fields are required for registration.", "warning")
            return render_template("register.html")

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        conn = None
        try:
            conn = pymysql.connect(**connection_params)
            with conn.cursor() as cursor:
                sql = "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)"
                cursor.execute(sql, (username, email, hashed_password))
                conn.commit()
                flash("Registration successful! Please log in.", "success")
                return redirect(url_for("login"))
        except pymysql.IntegrityError:
            flash("Username or email already exists.", "danger")
        except pymysql.MySQLError as e:
             print(f"Registration DB Error: {e}")
             flash("An error occurred during registration. Please try again.", "danger")
        finally:
            if conn and conn.open:
                conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'is_admin', False):
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('dashboard'))

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        remember = True if request.form.get('remember') else False

        if not email or not password:
            flash("Email and password are required.", "warning")
            return render_template("login.html")

        conn = None
        try:
            conn = pymysql.connect(**connection_params)
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # Verify JOIN column u.SHELTER_ID exists and links correctly
                sql = """
                    SELECT
                        u.id, u.username, u.email, u.password_hash, u.admin,
                        s.SHELTER_ID, s.NAME as SHELTER_NAME
                    FROM users u
                    LEFT JOIN SHELTERS s ON u.SHELTER_ID = s.SHELTER_ID
                    WHERE u.email = %s
                """
                cursor.execute(sql, (email,))
                user_data = cursor.fetchone()

            if user_data and bcrypt.check_password_hash(user_data["password_hash"], password):
                is_admin_flag = user_data.get('admin', 0)
                shelter_id_val = user_data.get('SHELTER_ID') if is_admin_flag == 1 else None
                shelter_name_val = user_data.get('SHELTER_NAME') if is_admin_flag == 1 and shelter_id_val else None

                user_obj = User(
                    id=user_data["id"],
                    username=user_data["username"],
                    email=user_data["email"],
                    is_admin=is_admin_flag,
                    shelter_id=shelter_id_val,
                    shelter_name=shelter_name_val
                )
                login_user(user_obj, remember=remember)
                flash("Login successful!", "success")

                next_page = request.args.get('next')
                if next_page and not next_page.startswith('/'):
                    next_page = None

                if user_obj.is_admin:
                    # Ensure admin has shelter ID before redirecting to admin area
                    if not user_obj.shelter_id:
                         flash("Admin account setup incomplete (no shelter linked). Please contact support.", "warning")
                         logout_user()
                         return redirect(url_for('login'))
                    return redirect(next_page or url_for('admin_dashboard'))
                else:
                    return redirect(next_page or url_for('dashboard'))
            else:
                flash("Invalid email or password.", "danger")

        except pymysql.MySQLError as e:
            print(f"Login DB Error: {e}")
            flash("An error occurred during login. Please try again.", "danger")
        except Exception as e:
            print(f"Login General Error: {e}")
            flash("An unexpected error occurred.", "danger")
        finally:
            if conn and conn.open:
                conn.close()

    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    if getattr(current_user, 'is_admin', False):
        return redirect(url_for('admin_dashboard'))
    conn = None
    adopted_pets_count = 0
    recent_adoptions = []
    under_process_count = 0
    try:
        conn = pymysql.connect(**connection_params)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT P.NAME as NAME, P.BREED as BREED, A.ADOPTION_STATUS as STATUS, A.ADOPTION_DATE as application_date
                FROM ADOPTIONS A
                JOIN PETS P ON A.PET_ID = P.PET_ID
                WHERE A.ADOPTER_ID = %s
                ORDER BY A.ADOPTION_DATE DESC
                LIMIT 5
            """, (current_user.id,))
            recent_adoptions = cursor.fetchall()
            cursor.execute("SELECT COUNT(*) as c FROM ADOPTIONS WHERE ADOPTION_STATUS = 'Successful' AND ADOPTER_ID = %s", (current_user.id,))
            adopted_pets_count = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM ADOPTIONS WHERE ADOPTION_STATUS IN ('Underway', 'Pending') AND ADOPTER_ID = %s", (current_user.id,))
            under_process_count = cursor.fetchone()["c"]
    except pymysql.MySQLError as e:
        print(f"Dashboard DB Error: {e}")
        flash("Could not load dashboard data due to a database error.", "warning")
    finally:
        if conn and conn.open:
            conn.close()

    return render_template(
        'dashboard.html',
        recent_adoptions=recent_adoptions,
        adopted_pets_count=adopted_pets_count,
        under_process_count=under_process_count
    )

@app.route("/logout")
@login_required
def logout():
    target_url = url_for("login")
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(target_url)

@app.route('/my-pets')
@login_required
def my_pets():
    if getattr(current_user, 'is_admin', False):
        flash("Admins manage pets via the admin dashboard.", "info")
        return redirect(url_for('admin_dashboard'))

    adopted_pets_list = []
    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql_query = """
                SELECT
                    P.PET_ID, P.NAME, P.SPECIES, P.BREED, P.COLOR,
                    P.AGE AS AGE_AT_ADOPTION,
                    A.ADOPTION_DATE
                FROM ADOPTIONS A
                JOIN PETS P ON A.PET_ID = P.PET_ID
                WHERE A.ADOPTER_ID = %s AND A.ADOPTION_STATUS = 'Successful'
                ORDER BY A.ADOPTION_DATE DESC
            """
            cursor.execute(sql_query, (current_user.id,))
            adopted_pets_list = cursor.fetchall()
    except pymysql.MySQLError as e:
        print(f"Database error fetching adopted pets: {e}")
        flash("Could not retrieve your adopted pets due to a database error.", "danger")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        flash("An unexpected error occurred while fetching your pets.", "danger")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template('my_pets.html', adopted_pets=adopted_pets_list)


# === General Site Routes ===
@app.route('/')
def home():
    connection = None
    total_adoption_count = 0
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM ADOPTIONS WHERE ADOPTION_STATUS = 'Successful'")
            result = cursor.fetchone()
            if result:
                total_adoption_count = result['count']
    except pymysql.MySQLError as e:
         print(f"Home Page DB Error: {e}")
    finally:
        if connection and connection.open:
            connection.close()
    return render_template('index.html', total_adoptions=f"{total_adoption_count:,}")


# === PET Routes ===
@app.route('/pets')
def pets():
    connection = None
    pets_list = []
    species_list = []
    age_list = []
    shelter_list = []
    color_list = []
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT P.*, S.NAME AS SHELTER_NAME, S.SHELTER_ID
                FROM PETS P
                JOIN SHELTERS S ON P.SHELTER_ID = S.SHELTER_ID
                WHERE P.PET_ID NOT IN (
                    SELECT PET_ID FROM ADOPTIONS WHERE ADOPTION_STATUS IN ('Successful','Underway')
                )
                ORDER BY P.PET_ID
            """)
            pets_list = cursor.fetchall()

            cursor.execute("SELECT DISTINCT SPECIES FROM PETS ORDER BY SPECIES")
            species_list = [row['SPECIES'] for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT AGE FROM PETS ORDER BY AGE ASC")
            age_list = sorted(list(set(str(row['AGE']) for row in pets_list if row.get('AGE') is not None)))

            cursor.execute("SELECT NAME FROM SHELTERS ORDER BY NAME")
            shelter_list = [row['NAME'] for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT COLOR FROM PETS ORDER BY COLOR")
            color_list = sorted([row['COLOR'] for row in cursor.fetchall() if row.get('COLOR')])
    except pymysql.MySQLError as e:
         print(f"Pets Page DB Error: {e}")
         flash("Could not load pet listings due to a database error.", "warning")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template('pets.html', dogs=pets_list, species_list=species_list, age_list=age_list, shelter_list=shelter_list, color_list=color_list)


@app.route('/pet/<pet_id>')
def pet_details(pet_id):
    conn = None
    pet = None
    try:
        conn = pymysql.connect(**connection_params)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute('''
                SELECT P.*, S.NAME AS shelter_name, S.SHELTER_ID
                FROM PETS P
                JOIN SHELTERS S ON P.SHELTER_ID = S.SHELTER_ID
                WHERE P.PET_ID = %s''', (pet_id,))
            pet = cursor.fetchone()

    except pymysql.MySQLError as e:
         print(f"Pet Detail DB Error: {e}")
         flash("Could not load pet details.", "warning")
    finally:
        if conn and conn.open:
            conn.close()

    if pet is None:
        flash("Pet not found.", "danger")
        return redirect(url_for('pets'))

    return render_template('pet.html', pet=pet)


# === SHELTER Routes ===

def load_shelters(location_filter=None):
    connection = None
    shelters = []
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor: # Use DictCursor here too
            query = "SELECT * FROM SHELTERS"
            params = []
            if location_filter:
                query += " WHERE LOCATION = %s" # Assuming LOCATION column exists
                params.append(location_filter)
            query += " ORDER BY NAME"
            cursor.execute(query, params)
            shelters = cursor.fetchall()
    except pymysql.MySQLError as e:
         print(f"Load Shelters DB Error: {e}")
         # Handle error silently or flash message
    finally:
        if connection and connection.open:
            connection.close()
    return shelters


@app.route('/shelter/<shelter_id>')
def shelter_details(shelter_id):
    connection = None
    shelter = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM SHELTERS WHERE SHELTER_ID = %s", (shelter_id,))
            shelter = cursor.fetchone()
    except pymysql.MySQLError as e:
         print(f"Shelter Detail DB Error: {e}")
         flash("Could not load shelter details.", "warning")
    finally:
        if connection and connection.open:
            connection.close()

    if not shelter:
        flash("Shelter not found!", "danger")
        return redirect(url_for('shelters'))

    return render_template('shelter.html', shelter=shelter)


@app.route('/shelter/<shelter_id>/pets')
def shelter_pets(shelter_id):
    connection = None
    pets = []
    shelter_name = "Unknown Shelter"
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
             # Get shelter name first
            cursor.execute("SELECT NAME FROM SHELTERS WHERE SHELTER_ID = %s", (shelter_id,))
            shelter_data = cursor.fetchone()
            if shelter_data:
                shelter_name = shelter_data['NAME']

                # Get available pets for this shelter
                cursor.execute("""
                    SELECT P.*, S.NAME AS SHELTER_NAME
                    FROM PETS P
                    JOIN SHELTERS S ON P.SHELTER_ID = S.SHELTER_ID
                    WHERE P.SHELTER_ID = %s
                    AND P.PET_ID NOT IN (SELECT PET_ID FROM ADOPTIONS WHERE ADOPTION_STATUS = 'Successful')
                    ORDER BY P.DATE_LISTED DESC
                """, (shelter_id,))
                pets = cursor.fetchall()
            else:
                 flash("Shelter not found.", "warning") # Shelter itself doesn't exist
                 return redirect(url_for('shelters'))

    except pymysql.MySQLError as e:
         print(f"Shelter Pets DB Error: {e}")
         flash("Could not load pets for this shelter.", "warning")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template('shelter_pets.html', pets=pets, shelter_name=shelter_name, shelter_id=shelter_id)


@app.route('/shelters')
def shelters():
    location_filter = request.args.get('location') # Example filter query param
    shelters_list = load_shelters(location_filter)
    # Add logic to get unique locations for filter dropdown if needed
    return render_template('shelter_all.html', shelters=shelters_list)


# === ADOPTION Routes ===
@app.route("/adopt/<pet_id>", methods=["GET", "POST"])
@login_required 
def adopt_pet(pet_id):
    conn = None
    try:
        conn = pymysql.connect(**connection_params)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # --- Initial Checks ---
            # Check if pet exists and is available
            cursor.execute("""
                SELECT P.*
                FROM PETS P
                LEFT JOIN ADOPTIONS A ON P.PET_ID = A.PET_ID AND A.ADOPTION_STATUS = 'Successful'
                WHERE P.PET_ID = %s AND A.ADOPTION_ID IS NULL
                """, (pet_id,))
            pet = cursor.fetchone()
            if not pet:
                flash("Pet not found or already adopted!", "danger")
                return redirect(url_for("pets"))

            # Check if user has already started adoption for this pet
            cursor.execute("SELECT ADOPTION_ID FROM ADOPTIONS WHERE PET_ID = %s AND ADOPTER_ID = %s", (pet_id, current_user.id))
            existing_adoption = cursor.fetchone()
            if existing_adoption:
                flash("You have already started the adoption process for this pet!", "warning")
                return redirect(url_for("dashboard")) # Redirect to dashboard to see status

            # --- Check if ADOPTER info exists ---
            cursor.execute("SELECT ADOPTER_ID FROM ADOPTER WHERE ADOPTER_ID = %s", (current_user.id,))
            adopter_exists = cursor.fetchone()

            if not adopter_exists:
                # --- Adopter Info Form Handling ---
                if request.method == "POST":
                    age = request.form.get("age")
                    gender_form = request.form.get("gender")
                    # Add validation for age/gender
                    if not age or not gender_form or not age.isdigit() or int(age) <= 0:
                        flash("Please provide a valid age and gender.", "warning")
                        # Re-render the form, passing pet_id back
                        return render_template("adopter_info.html", pet_id=pet_id)

                    gender_db = 'O' # Default to Other
                    if gender_form == 'Male':
                        gender_db = 'M'
                    elif gender_form == "Female":
                        gender_db = 'F'

                    try:
                        # Insert adopter info
                        cursor.execute(
                            "INSERT INTO ADOPTER (ADOPTER_ID, NAME, AGE, GENDER) VALUES (%s, %s, %s, %s)",
                            (current_user.id, current_user.username, int(age), gender_db),
                        )
                        # --- IMPORTANT: Commit ONLY the adopter info insert here ---
                        conn.commit()
                        flash("Your adopter information has been saved.", "info")
                        # Now that adopter info exists, redirect back to start the adoption record insert
                        # This avoids complex state management in one request
                        return redirect(url_for("adopt_pet", pet_id=pet_id))
                    except pymysql.MySQLError as e:
                         print(f"Adopter Insert DB Error: {e}")
                         conn.rollback()
                         flash("Could not save adopter information. Please try again.", "danger")
                         return render_template("adopter_info.html", pet_id=pet_id)

                else: # GET request and adopter info needed
                    # Show the form to collect adopter info
                    return render_template("adopter_info.html", pet_id=pet_id)

            # --- Adopter Info Exists - Proceed to create adoption record ---
            # This part is reached either directly (if adopter existed)
            # or after the POST->redirect from the adopter_info form.
            # Since it's reached via GET after the redirect, no POST check needed here.

            # Get Pet's Shelter ID and Amount again (safer than relying on previous fetches)
            cursor.execute("SELECT SHELTER_ID, Amount FROM PETS WHERE PET_ID = %s", (pet_id,))
            details = cursor.fetchone()
            if not details: # Should not happen if first check passed, but good practice
                 flash("Could not retrieve pet details for adoption.", "danger")
                 return redirect(url_for("pets"))

            # Insert adoption record
            try:
                sql_insert = """
                    INSERT INTO ADOPTIONS
                        (PET_ID, SHELTER_ID, ADOPTER_ID, ADOPTION_STATUS, ADOPTION_DATE, PAYMENT_STATUS, AMOUNT)
                    VALUES
                        (%s, %s, %s, 'Underway', NOW(), 'Pending', %s)
                """
                cursor.execute(sql_insert, (pet_id, details['SHELTER_ID'], current_user.id, int(details['Amount'])))
                conn.commit() # Commit the adoption record insert
                flash(f"Adoption process for {pet['NAME']} started successfully! Check your dashboard for status.", "success")
                return redirect(url_for("dashboard"))
            except pymysql.MySQLError as e:
                 print(f"Adoption Insert DB Error: {e}")
                 conn.rollback()
                 flash("Could not start the adoption process due to a database error.", "danger")
                 return redirect(url_for("pets")) # Redirect somewhere sensible on failure

    except pymysql.MySQLError as e:
         print(f"Adopt Pet DB Error: {e}")
         flash("A database error occurred. Please try again later.", "danger")
         return redirect(url_for("pets"))
    except Exception as e:
        print(f"Adopt Pet General Error: {e}")
        flash("An unexpected error occurred.", "danger")
        return redirect(url_for("pets"))
    finally:
        if conn and conn.open:
            conn.close()

    # Fallback redirect (should ideally not be reached)
    return redirect(url_for("pets"))


# === ADMIN Routes ===

@app.route('/admin/login', methods=['GET'])
def admin_login():
    # Main login handles logic now, just show the page if needed by URL
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
         return redirect(url_for('admin_dashboard'))
    # Consider removing this route and just using /login?
    return render_template('admin/admin_login.html')


@app.route('/admin/logout')
@login_required
def admin_logout():
    # Check if it's actually an admin logging out, though not strictly necessary
    # if not getattr(current_user, 'is_admin', False):
    #     return redirect(url_for('home')) # Or regular dashboard?

    logout_user()
    flash("You have been logged out from the admin area.", "info")
    return redirect(url_for('login')) # Redirect to main login page


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    shelter_id = current_user.shelter_id
    stats = {'pending_adoptions_count': 0, 'listed_pets_count': 0, 'total_adopted_count': 0}
    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM ADOPTIONS WHERE SHELTER_ID = %s AND ADOPTION_STATUS IN ('Pending', 'Underway')", (shelter_id,))
            stats['pending_adoptions_count'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM PETS P LEFT JOIN ADOPTIONS A ON P.PET_ID = A.PET_ID AND A.ADOPTION_STATUS = 'Successful' WHERE P.SHELTER_ID = %s AND A.ADOPTION_ID IS NULL", (shelter_id,)) # Count only available pets
            stats['listed_pets_count'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM ADOPTIONS WHERE SHELTER_ID = %s AND ADOPTION_STATUS = 'Successful'", (shelter_id,))
            stats['total_adopted_count'] = cursor.fetchone()['count']

    except pymysql.MySQLError as e:
        print(f"Dashboard DB error: {e}")
        flash("Could not load dashboard statistics.", "warning")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template('admin/admin_dashboard.html', **stats)


@app.route('/admin/add_pet', methods=['GET', 'POST'])
@admin_required
def admin_add_pet():
    if request.method == 'POST':
        name = request.form.get('name')
        species = request.form.get('species')
        breed = request.form.get('breed')
        color = request.form.get('color')
        age = request.form.get('age')
        height = request.form.get('height') or None
        weight = request.form.get('weight') or None
        description = request.form.get('description') or None
        amount = request.form.get('amount')

        if not all([name, species, breed, color, age, amount]):
            flash("Please fill in all required fields.", "warning")
            return render_template('admin/admin_add_pet.html')

        try:
            age_val = float(age)
            amount_val = int(amount)
            height_val = int(height) if height else None
            weight_val = float(weight) if weight else None
            shelter_id = current_user.shelter_id

            connection = None
            try:
                connection = pymysql.connect(**connection_params)
                with connection.cursor() as cursor:
                    sql = """
                        INSERT INTO PETS (NAME, SPECIES, BREED, COLOR, AGE, HEIGHT, WEIGHT, MISC, AMOUNT, SHELTER_ID)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (name, species, breed, color, age_val, height_val, weight_val, description, amount_val, shelter_id))
                connection.commit()
                flash(f"Successfully added '{name}'!", "success")
                return redirect(url_for('admin_dashboard'))

            except pymysql.MySQLError as e:
                print(f"Add Pet DB error: {e}")
                if connection: connection.rollback()
                flash("Database error adding pet.", "danger")
            finally:
                if connection and connection.open:
                    connection.close()

        except ValueError:
             flash("Invalid number for age, height, weight, or amount.", "danger")

    return render_template('admin/admin_add_pet.html')


@app.route('/admin/adoptions')
@admin_required
def admin_view_adoptions():
    shelter_id = current_user.shelter_id
    adoptions_list = []
    distinct_statuses_list = []
    filter_status = request.args.get('status', '').strip()
    filter_pet_name = request.args.get('pet_name', '').strip()
    filter_adopter_name = request.args.get('adopter_name', '').strip() # New
    filter_adopter_email = request.args.get('adopter_email', '').strip() # New
    sort_by = request.args.get('sort_by', 'ADOPTION_DATE')
    sort_order = request.args.get('sort_order', 'DESC')
    allowed_sort_columns = {
        'adopter_name': 'U.username',
        'pet_name': 'P.NAME',
        'ADOPTION_DATE': 'A.ADOPTION_DATE',
        'ADOPTION_STATUS': 'A.ADOPTION_STATUS',
    }
    db_sort_column = allowed_sort_columns.get(sort_by, 'A.ADOPTION_DATE')
    if sort_order.upper() not in ['ASC', 'DESC']:
        sort_order = 'DESC'

    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT DISTINCT ADOPTION_STATUS FROM ADOPTIONS
                WHERE SHELTER_ID = %s ORDER BY ADOPTION_STATUS
            """, (shelter_id,))
            distinct_statuses_list = [row['ADOPTION_STATUS'] for row in cursor.fetchall()]

            params = [shelter_id]
            sql = """
                SELECT
                    A.ADOPTION_ID, A.ADOPTION_STATUS, A.ADOPTION_DATE,
                    P.PET_ID, P.NAME as pet_name, P.BREED as pet_breed,
                    U.id as adopter_id, U.username as adopter_name, U.email as adopter_email
                FROM ADOPTIONS A
                JOIN PETS P ON A.PET_ID = P.PET_ID
                JOIN users U ON A.ADOPTER_ID = U.id
                WHERE A.SHELTER_ID = %s
            """
            if filter_status:
                if filter_status == 'Pending':
                    sql += " AND A.ADOPTION_STATUS IN ('Pending', 'Underway')"
                elif filter_status == 'Accepted':
                    sql += " AND A.ADOPTION_STATUS IN ('Accepted', 'Successful')"
                elif filter_status == 'Rejected':
                    sql += " AND A.ADOPTION_STATUS IN ('Rejected', 'Cancelled')"
                else:
                    sql += " AND A.ADOPTION_STATUS = %s"
                    params.append(filter_status)

            if filter_pet_name:
                sql += " AND P.NAME LIKE %s"
                params.append(f"%{filter_pet_name}%")

            if filter_adopter_name:
                sql += " AND U.username LIKE %s"
                params.append(f"%{filter_adopter_name}%")

            if filter_adopter_email:
                sql += " AND U.email LIKE %s"
                params.append(f"%{filter_adopter_email}%")
            sql += f" ORDER BY {db_sort_column} {sort_order.upper()}"

            cursor.execute(sql, params)
            adoptions_list = cursor.fetchall()

    except pymysql.MySQLError as e:
        print(f"View Adoptions DB error: {e}")
        flash("Could not retrieve adoption records.", "danger")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template(
        'admin/admin_view_adoptions.html',
        adoptions=adoptions_list,
        distinct_statuses=distinct_statuses_list
    )


@app.route('/admin/update_adoption_status/<int:adoption_id>', methods=['POST'])
@admin_required
def admin_update_adoption_status(adoption_id):
    new_status = request.form.get('new_status')
    shelter_id = current_user.shelter_id
    allowed_statuses = [ 'Successful', 'Cancelled', 'Underway'] # Keep synced with DB/Forms

    if not new_status or new_status not in allowed_statuses:
        flash("Invalid status provided.", "warning")
        return redirect(url_for('admin_view_adoptions'))

    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor: # Use DictCursor to check shelter_id by name
            cursor.execute("SELECT SHELTER_ID FROM ADOPTIONS WHERE ADOPTION_ID = %s", (adoption_id,))
            result = cursor.fetchone()

            # Security Check: Verify adoption belongs to admin's shelter
            if not result or result['SHELTER_ID'] != shelter_id:
                flash("Permission denied to update this adoption record.", "danger")
                return redirect(url_for('admin_view_adoptions'))

            # Proceed with update
            cursor.execute("UPDATE ADOPTIONS SET ADOPTION_STATUS = %s WHERE ADOPTION_ID = %s", (new_status, adoption_id))
            connection.commit()
            flash(f"Adoption #{adoption_id} status updated to '{new_status}'.", "success")

    except pymysql.MySQLError as e:
        print(f"Update Status DB error: {e}")
        if connection: connection.rollback()
        flash("Database error updating status.", "danger")
    finally:
        if connection and connection.open:
            connection.close()

    return redirect(url_for('admin_view_adoptions'))

@app.route('/admin/my_listings')
@admin_required
def admin_my_listings():
    shelter_id = current_user.shelter_id
    pets_list = []
    distinct_species_list = []

    # Get filter parameters from URL query string
    search_name = request.args.get('name', '').strip()
    filter_species = request.args.get('species', '').strip()
    filter_status = request.args.get('status', '').strip() # e.g., 'Available', 'Pending', 'Adopted'

    connection = None
    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # --- Fetch Distinct Species for Filter Dropdown ---
            cursor.execute("SELECT DISTINCT SPECIES FROM PETS WHERE SHELTER_ID = %s ORDER BY SPECIES", (shelter_id,))
            distinct_species_list = [row['SPECIES'] for row in cursor.fetchall()]

            # --- Build Dynamic Query for Pets ---
            sql_base = """
                SELECT
                    P.*,
                    CASE
                        WHEN A.ADOPTION_STATUS = 'Successful' THEN 'Adopted'
                        WHEN A.ADOPTION_STATUS IN ('Pending', 'Underway') THEN 'Pending'
                        WHEN A.ADOPTION_ID IS NULL THEN 'Available'
                        ELSE A.ADOPTION_STATUS -- Or handle other statuses
                    END AS adoption_status
                    -- , PI.filename as IMAGE_FILENAME -- Example if you have pet images table
                FROM
                    PETS P
                LEFT JOIN (
                    -- Get the latest non-cancelled adoption status for each pet
                    SELECT PET_ID, ADOPTION_STATUS, ADOPTION_ID
                    FROM ADOPTIONS ad1
                    WHERE ad1.ADOPTION_DATE = (
                        SELECT MAX(ad2.ADOPTION_DATE)
                        FROM ADOPTIONS ad2
                        WHERE ad1.PET_ID = ad2.PET_ID
                          AND ad2.ADOPTION_STATUS != 'Cancelled'
                    ) AND ad1.ADOPTION_STATUS != 'Cancelled'
                    -- Or simpler if only one adoption attempt matters:
                    -- FROM ADOPTIONS WHERE ADOPTION_STATUS != 'Cancelled'
                ) A ON P.PET_ID = A.PET_ID
                -- LEFT JOIN PET_IMAGES PI ON P.PET_ID = PI.PET_ID AND PI.is_primary = 1 -- Example join for image
                WHERE P.SHELTER_ID = %s
            """
            params = [shelter_id]

            # Add filters conditionally
            if search_name:
                sql_base += " AND P.NAME LIKE %s"
                params.append(f"%{search_name}%") # Use wildcard search

            if filter_species:
                sql_base += " AND P.SPECIES = %s"
                params.append(filter_species)

            # Filter by calculated adoption_status (use HAVING clause)
            if filter_status == 'Available':
                 # Pets with no adoption record or only cancelled ones
                 sql_base += " AND A.ADOPTION_ID IS NULL"
            elif filter_status == 'Pending':
                 sql_base += " AND A.ADOPTION_STATUS IN ('Pending', 'Underway')"
            elif filter_status == 'Adopted':
                 sql_base += " AND A.ADOPTION_STATUS = 'Successful'"


            sql_base += " ORDER BY P.PET_ID DESC"
            cursor.execute(sql_base, params)
            pets_list = cursor.fetchall()

    except pymysql.MySQLError as e:
        print(f"My Listings DB error: {e}")
        flash("Could not retrieve your pet listings due to a database error.", "warning")
    finally:
        if connection and connection.open:
            connection.close()

    return render_template(
        'admin/admin_listings.html',
        pets=pets_list,
        distinct_species=distinct_species_list
    )

@app.route('/admin/get_medical_records/<int:pet_id>')
@admin_required
def get_medical_records(pet_id):
    """
    Fetches medical records for a specific pet belonging to the admin's shelter.
    Returns JSON data.
    """
    shelter_id = current_user.shelter_id
    records = []
    connection = None

    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Security Check: Verify the pet belongs to the admin's shelter first
            cursor.execute("SELECT SHELTER_ID FROM PETS WHERE PET_ID = %s", (pet_id,))
            pet_info = cursor.fetchone()

            if not pet_info or pet_info['SHELTER_ID'] != shelter_id:
                # Return an error response if pet not found or doesn't belong to shelter
                return jsonify({'error': 'Pet not found or access denied'}), 404

            # Fetch medical records, ordering by date (most recent first)
            sql_records = """
                SELECT PET_ID, `DATE`, VET_NAME, TREATMENT, MEDICINE
                FROM MEDICINES
                WHERE PET_ID = %s
                ORDER BY `DATE` DESC
            """
            cursor.execute(sql_records, (pet_id,))
            records = cursor.fetchall()

            # Convert date objects to strings for JSON compatibility
            for record in records:
                if record['DATE']:
                    record['DATE'] = record['DATE'].strftime('%Y-%m-%d')

    except pymysql.MySQLError as e:
        print(f"Get Medical Records DB error for pet {pet_id}: {e}")
        return jsonify({'error': 'Database error fetching records'}), 500
    except Exception as e:
        print(f"Get Medical Records unexpected error for pet {pet_id}: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        if connection and connection.open:
            connection.close()
    print(records)
    # Return the fetched records as JSON
    return jsonify({'records': records})


@app.route('/admin/add_medical_record/<int:pet_id>', methods=['POST'])
@admin_required
def add_medical_record(pet_id):
    """
    Adds a new medical record for a specific pet belonging to the admin's shelter.
    Expects POST data: record_type, record_date, record_notes
    (Combines treatment/medicine based on type/notes for simplicity here)
    Returns JSON response.
    """
    shelter_id = current_user.shelter_id
    connection = None

    # Get data from form POST request
    record_type = request.form.get('record_type') # e.g., Vaccination, Check-up, Note
    record_date = request.form.get('record_date') # Expects YYYY-MM-DD string
    record_notes = request.form.get('record_notes') # Maps to TREATMENT or MEDICINE
    # Optional: Add VET_NAME if you add a field for it in the modal form
    vet_name = request.form.get('vet_name', 'Shelter Staff') # Default or get from form

    # Basic Validation
    if not all([record_type, record_date, record_notes]):
        return jsonify({'error': 'Missing required fields (type, date, notes)'}), 400

    try:
        connection = pymysql.connect(**connection_params)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Security Check: Verify the pet belongs to the admin's shelter
            cursor.execute("SELECT SHELTER_ID FROM PETS WHERE PET_ID = %s", (pet_id,))
            pet_info = cursor.fetchone()

            if not pet_info or pet_info['SHELTER_ID'] != shelter_id:
                return jsonify({'error': 'Pet not found or access denied'}), 403 # Forbidden

            # Determine TREATMENT and MEDICINE based on type/notes
            # Simple logic: If type is Medication, put in MEDICINE, otherwise TREATMENT
            treatment_val = None
            medicine_val = None
            if record_type == 'Medication':
                medicine_val = record_notes
                treatment_val = record_type # Or keep it more specific if needed
            elif record_type == 'Vaccination' or record_type == 'Check-up' or record_type == 'Procedure':
                 treatment_val = f"{record_type}: {record_notes}" # Combine type and notes
            else: # Default to putting in TREATMENT
                treatment_val = record_notes

            # Insert the new record
            sql_insert = """
                INSERT INTO MEDICINES (PET_ID, `DATE`, VET_NAME, TREATMENT, MEDICINE)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql_insert, (pet_id, record_date, vet_name, treatment_val, medicine_val))
            connection.commit()

            # Return success response
            return jsonify({'success': True, 'message': 'Medical record added successfully.'}), 201 # 201 Created

    except pymysql.MySQLError as e:
        print(f"Add Medical Record DB error for pet {pet_id}: {e}")
        if connection: connection.rollback()
        return jsonify({'error': 'Database error saving record'}), 500
    except ValueError as ve: # Catch potential date conversion errors if needed
        print(f"Add Medical Record Value error for pet {pet_id}: {ve}")
        return jsonify({'error': 'Invalid data format (e.g., date)'}), 400
    except Exception as e:
        print(f"Add Medical Record unexpected error for pet {pet_id}: {e}")
        if connection: connection.rollback()
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        if connection and connection.open:
            connection.close()



if __name__ == '__main__':
    app.run( debug=True,host='0.0.0.0')