from jinja2 import StrictUndefined

from flask import Flask, render_template, redirect, request, flash, session, url_for, jsonify, Markup
from flask_debugtoolbar import DebugToolbarExtension
from flask import Response
from flask.ext.bcrypt import Bcrypt
import json

from model import connect_to_db, db
from model import User, SupplyDetail, Project, ProjectSupply, Item

from helpers import get_all_supply_types, get_all_supply_units, get_all_brands, get_all_colors, get_matching_sd
from helpers import get_all_brands_by_supply_type, get_all_units_by_supply_type
from helpers import craft_project_supplies_info, get_filtered_inventory, get_inventory_by_search, get_projects_by_search
from helpers import get_inventory_chart_dict, get_colors_from_brand, get_all_colors_dict_by_brand
from helpers import add_item_to_inventory, get_matching_item, update_item_record
from helpers import add_supply_to_db, add_user_to_db

app = Flask(__name__)
bcrypt = Bcrypt(app)

# Required to use Flask sessions and the debug toolbar
app.secret_key = "ABC"

# Normally, if you use an undefined variable in Jinja2, it fails
# silently. This is horrible. Fix this so that, instead, it raises an error.
app.jinja_env.undefined = StrictUndefined


@app.route("/")
def index():
    """Homepage."""

    # Check whether the user is logged in. If so, get the user, so we can
    # display user-specific info on the homepage.
    user_id = session.get("user_id")

    if user_id:
        user = User.query.get(user_id)
    else:
        user = None
    return render_template("homepage.html", user=user)


################################################################
# General dashboard routes (show dash, get data for dash, etc.)
################################################################

@app.route('/dashboard')
def show_dashboard():
    """Show a user's dashboard."""

    # Get the user's id from the session, if possible.
    user_id = session.get("user_id")

    if user_id:
        # Get the current user's inventory details as a list of tuples of the
        # format: (type, brand, color, units, url, qty)
        inventory = db.session.query(SupplyDetail.supply_type,
                                     SupplyDetail.brand,
                                     SupplyDetail.color,
                                     SupplyDetail.units,
                                     SupplyDetail.purchase_url,
                                     Item.qty,
                                     Item.item_id).outerjoin(Item).filter_by(user_id=user_id).all()

        inventory = sorted(inventory)

        # Get the user's projects.
        projects = Project.query.filter(Project.user_id == user_id).all()

        # Prepare data for the "Add a Supply", "Filter Inventory View", and
        # "Search Your Inventory" features.
        all_supply_types = get_all_supply_types()
        all_brands = get_all_brands()
        all_colors = get_all_colors()

        table_body = Markup(render_template("supply_table.html", inventory=inventory))
        inventory_chart = Markup(render_template("inventory-chart.html"))

        # Render a dashboard showing the user's inventory.
        return render_template("dashboard.html",
                               projects=projects,
                               all_supply_types=all_supply_types,
                               all_brands=all_brands,
                               all_colors=all_colors,
                               table_body=table_body,
                               inventory_chart=inventory_chart)

    else:
        flash("You can't go there! Please log in.")
        return redirect("/")


@app.route("/supply-types.json")
def supply_types_data():
    """Return data about supplies in a user's inventory."""

    user_id = session.get("user_id")
    data_dict = get_inventory_chart_dict(user_id)
    return data_dict


#################################################################
# Inventory data manipulation routes (adding/updating supplies)
#################################################################
@app.route('/add-supply', methods=['POST'])
def add_supply():
    """Add a supply to the user's inventory.

    This route responds to a POST request by adding a new record
    to the items table with the current authenticated user's id, the supply_detail's
    id, and the quantity given. If the supply_detail doesn't exist, we create one
    and add it to the database.
    """

    user_id = session.get("user_id")

    supply_type = request.form.get("supplytype")
    brand = request.form.get("brand")
    color = request.form.get("color")
    units = request.form.get("units")
    qty = request.form.get("quantity-owned")

    sd_from_db = get_matching_sd(supply_type, brand, color)

    # FIXME: Move more logic into helper functions!

    # If the supply detail exists...
    if sd_from_db:

        # Create an item object.
        item_from_db = get_matching_item(user_id, sd_from_db.sd_id)

        # If that item exists...
        if item_from_db:

            # Just update the record.
            result = update_item(item_from_db, int(qty))
            flash(result)

        # Otherwise, add the item to the user's inventory.
        else:
            add_item_to_inventory(user_id, sd_from_db.sd_id, qty)
            flash("%s %s of %s %s have been added to your inventory." %
                 (qty, units, brand, supply_type))

    # If the detail doesn't exist, create a new supply detail, add it,
    # and add an item to the inventory with those details.
    else:
        new_sd = add_supply_to_db(supply_type, brand, color, units)
        add_item_to_inventory(user_id, new_sd.sd_id, qty)

        flash("Whoa, this is new! %s %s of %s %s %s have been added to your inventory." %
             (qty, units, color, brand, supply_type))

    return redirect(url_for('.show_dashboard'))


@app.route("/update-item", methods=["POST"])
def update_item():
    """Updates a row in the user's inventory based on values passed from AJAX."""

    # Get the item qty and its id
    new_qty = request.form.get("qty")
    item_id = request.form.get("itemID")

    # Instantiate the item
    item = Item.query.get(item_id)

    # Perform a wholesale overwrite.
    overwrite = True
    result = update_item_record(item, new_qty, overwrite)
    return result


# The next four routes fetch data that we need to add supplies.
@app.route("/dashboard/brands.json")
def get_brands():
    """Fetch all brands in the db by supply type, and return as JSON."""
    brands = get_all_brands_by_supply_type()
    brands = jsonify(brands)
    return(brands)


@app.route("/dashboard/units.json")
def get_units():
    """Fetch all units in the db by supply type, and return as JSON."""
    units = get_all_units_by_supply_type()
    units = jsonify(units)
    return(units)


@app.route("/typeahead/colors-by-brand.json")
def typeahead_colors():
    """Fetch tags for colors autocomplete feature in adding supplies."""

    # Get the brand from the URL args.
    brand = request.args.get("brand")

    # Get the list of colors for that brand.
    colors = get_colors_from_brand(brand)

    # JSONify the list (not to be confused w/ calling jsonify...)
    # and return it.
    return Response(json.dumps(colors), mimetype='application/json')


##########################################################
# Inventory filter/search routes
##########################################################

@app.route("/inventory/filter.html")
def filter_inventory():
    """Gives AJAX a filtered version of the HTML for the user's inventory, based on
    brand, supply type, or color."""

    # Get the brand, supply_type, and color from the GET request arguments.
    # Alse get the user_id from the session.
    brand = request.args.get("brand")
    supply_type = request.args.get("supplytype")
    color = request.args.get("color")
    user_id = session.get("user_id")

    # Fetch the filtered inventory as a list of tuples.
    inventory = get_filtered_inventory(user_id, brand, supply_type, color)

    # Render the HTML for the filtered inventory as a safe-to-use Markup object.
    table_body = Markup(render_template("supply_table.html", inventory=inventory))

    # Return the HTML to the AJAX request as a response.
    return table_body


@app.route("/inventory/search-results.html")
def search_inventory():
    """Returns only the rows in the user's inventory relevant to the passed
    search term."""

    # Get the string the user wanted to search for.
    search_term = request.args.get("search")
    user_id = session.get("user_id")

    # Get the user's inventory filtered by the search term, as a list of tuples.
    inventory = get_inventory_by_search(user_id, search_term)

    # Render HTML for search results as a safe-to-use Markup object.
    table_body = Markup(render_template("supply_table.html", inventory=inventory))

    return table_body


########################################################################
# Project routes (show project, show project creation form, handle form)
########################################################################

@app.route("/project/<int:project_id>")
def show_project(project_id):
    """Displays a page with all information about a project."""

    user_id = session.get("user_id")
    print "I'm the user ID", user_id

    # Get an object representing the project whose id was passed
    project = Project.query.get(project_id)

    # Get a dictionary representing all supply info for this project,
    # including the amount of any supplies a user must buy.
    project_supplies_info = craft_project_supplies_info(project, user_id)

    # Render the project page
    return render_template("project.html",
                           project=project,
                           project_supplies_info=project_supplies_info)


@app.route('/create-project', methods=['GET'])
def show_project_creation_form():
    """Displays the project creation form."""

    # Get the user info from the session.
    user_id = session.get("user_id")
    user = User.query.get(user_id)

    # Get the available supply types and units from db
    all_supply_types = get_all_supply_types()
    all_units = get_all_supply_units()

    return render_template("project_form.html",
                           user=user,
                           all_supply_types=all_supply_types,
                           all_units=all_units)


@app.route("/create-project", methods=["POST"])
def handle_project_creation():
    """Handles input from project creation form and adds project to database."""

    # Get the user info from the session.
    user_id = session.get("user_id")

    # Fetch basic project data from form
    title = request.form.get("title")
    description = request.form.get("description")
    instr_url = request.form.get("instr-url")
    img_url = request.form.get("img-url")

    #Create and commit project record
    project = Project(user_id=user_id,
                      title=title.title(),
                      description=description,
                      instr_url=instr_url,
                      img_url=img_url)

    db.session.add(project)
    db.session.commit()

    # Get supply info from form. First, we need the number of supplies from
    # the hidden field num-supplies.
    num_supplies = request.form.get("num-supplies")

    # Given num-supplies, we can iterate over the number of supplies to add
    # records to the db.

    # FIXME: Move project supply creation into a helper function.
    # Need to take the range of num_supplies + 1 or we won't get all supplies.
    for supply_num in range(int(num_supplies)+1):
        fieldname_num = str(supply_num)
        supply_type = request.form.get("supplytype"+fieldname_num)
        brand = request.form.get("brand"+fieldname_num)
        color = request.form.get("color"+fieldname_num)
        # units = request.form.get("units"+fieldname_num)
        qty = request.form.get("qty-required"+fieldname_num)

        # Get a supply from the db that matches the entered supply
        sd = get_matching_sd(supply_type, brand, color)

        print sd

        # Get the entered supply's id
        sd_id = sd.sd_id

        # Create and commit project supply record to db, so the entered
        # supply is associated with this project.

        project_supply = ProjectSupply(project_id=project.project_id,
                                       sd_id=sd_id,
                                       supply_qty=qty)

        db.session.add(project_supply)
        db.session.commit()

    flash("%s added to your projects. Hooray!" % (title))
    return redirect(url_for('.show_project', project_id=project.project_id))


@app.route("/create-project/new-supply-form.html")
def get_new_supply_form():
    """Generates a form for adding a new supply to a project."""

    all_supply_types = get_all_supply_types()
    form_num = request.args.get("counter")

    supply_form = render_template("project-supply-form.html",
                                  all_supply_types=all_supply_types,
                                  x=form_num)

    safe_supply_form = Markup(supply_form)

    return safe_supply_form


@app.route("/add-project/colors-by-brand.json")
def get_colors():
    """Fetch a dict of all colors in the db by brand, and return as JSON."""
    colors = get_all_colors_dict_by_brand()
    colors = jsonify(colors)
    return(colors)

@app.route("/projects/search-results.html")
def get_project_search_results():
    """Return HTML representing a table of projects that match the user's
    search query."""

    # Get the string the user wanted to search for.
    search_term = request.args.get("search")

    # Get a group of projects filtered by the search term, as a list of tuples.
    projects = get_projects_by_search(search_term)

    # Render HTML for search results as a safe-to-use Markup object.
    project_table_body = Markup(render_template("project_table.html", projects=projects))

    #return project_table_body
    return project_table_body


####################################################
# Registration routes
#
# These are based on code created in collaboration
# with rayramsay (https://github.com/rayramsay/).
####################################################

@app.route('/register', methods=['GET'])
def register_form():
    """Displays the registration form."""

    return render_template("register_form.html")


@app.route('/register', methods=['POST'])
def handle_register():
    """Handles input from registration form."""

    # Get the user's email, username, and password from the form.
    email = request.form.get("email")
    username = request.form.get("username")
    password = request.form.get("password")
    repeat_pw = request.form.get("repeat-pw")

    # Check whether the user exists.
    user = User.query.filter(User.username == username).first()

    # If that user exists, tell the user they can't have that username.
    if user:
        flash("That username has already been registered.")
        return redirect("/register")

    # Check whether the password and repeated passwords match.
    elif password != repeat_pw:
        flash("Entered passwords do not match.")
        return redirect("/register")

    else:
        # If the user doesn't exist, hash the password and create the user.
        pw_hash = bcrypt.generate_password_hash(password)
        add_user_to_db(email, username, pw_hash)
        print "############################################"
        print "############################################"
        print "User added w/ hash: ", pw_hash
        print "Given pw: ", password
        print "############################################"
        print "############################################"
        flash("Account created.")

        #Code 307 preserves the POST request, including form data.
        return redirect("/login", code=307)


####################################################
# Authentication/Deauthentication routes
#
# These are based on code created in collaboration
# with rayramsay (https://github.com/rayramsay/).
####################################################

@app.route('/login', methods=['GET'])
def login_form():
    """Displays the login form."""

    return render_template("login_form.html")


@app.route('/login', methods=['POST'])
def handle_login():
    """Handles input from login/registration form."""

    username = request.form.get("username")
    password = request.form.get("password")

    user = User.query.filter(User.username == username).first()
    pw_hash = user.password

    print "############################################"
    print "############################################"
    print "Hash from db: ", pw_hash
    print "typed pw: ", password
    print "############################################"
    print "############################################"

    if user:
        pw_is_correct = bcrypt.check_password_hash(pw_hash, password)
        if not pw_is_correct:
            flash("Incorrect username or password.")
            return redirect("/login")
        else:
            # Add their user_id to session
            session["user_id"] = user.user_id
            session["username"] = user.username

            flash("Welcome to Crafter's Closet!")
            return redirect("/dashboard")

    else:
        flash("Incorrect username or password.")
        return redirect("/login")


@app.route('/logout')
def logout():

    # Clear the session to log the user out and clear their cookie.
    session.clear()
    flash("See you later!")

    return redirect("/")


if __name__ == "__main__":
    # We have to set debug=True here, since it has to be True at the
    # point that we invoke the DebugToolbarExtension
    app.debug = True

    connect_to_db(app)

    # Use the DebugToolbar
    DebugToolbarExtension(app)

    app.run(host="0.0.0.0")
