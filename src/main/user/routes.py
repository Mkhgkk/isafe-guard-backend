from flask import Blueprint
from flask import current_app as app
from main.auth import token_required
from main.user.models import User

user_blueprint = Blueprint("user", __name__)

@user_blueprint.route("/", methods=["GET"])
@token_required
def get():
	"""Get user information
	---
	tags:
	  - User
	security:
	  - Bearer: []
	responses:
	  200:
	    description: User information retrieved successfully
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	        data:
	          type: object
	          description: User data
	  401:
	    description: Unauthorized - Invalid or missing token
	"""
	return User().get()

@user_blueprint.route("/auth", methods=["GET"])
def getAuth():
	"""Verify authentication status
	---
	tags:
	  - User
	responses:
	  200:
	    description: Authentication status
	    schema:
	      type: object
	      properties:
	        authenticated:
	          type: boolean
	          example: true
	"""
	return User().getAuth()

@user_blueprint.route("/login", methods=["POST"])
def login():
	"""User login
	---
	tags:
	  - User
	parameters:
	  - in: body
	    name: credentials
	    description: User login credentials
	    required: true
	    schema:
	      type: object
	      required:
	        - username
	        - password
	      properties:
	        username:
	          type: string
	          example: admin
	        password:
	          type: string
	          example: password123
	responses:
	  200:
	    description: Login successful
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	        token:
	          type: string
	          description: JWT authentication token
	  401:
	    description: Invalid credentials
	"""
	return User().login()

@user_blueprint.route("/logout", methods=["GET"])
def logout():
	"""User logout
	---
	tags:
	  - User
	responses:
	  200:
	    description: Logout successful
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	"""
	return User().logout()

@user_blueprint.route("/", methods=["POST"])
def add():
	"""Create new user
	---
	tags:
	  - User
	parameters:
	  - in: body
	    name: user
	    description: New user information
	    required: true
	    schema:
	      type: object
	      required:
	        - username
	        - password
	      properties:
	        username:
	          type: string
	          example: newuser
	        password:
	          type: string
	          example: password123
	        email:
	          type: string
	          example: user@example.com
	responses:
	  200:
	    description: User created successfully
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	  400:
	    description: Invalid input or user already exists
	"""
	return User().add()

@user_blueprint.route("/username", methods=["POST"])
@token_required
def update_username():
	"""Update username
	---
	tags:
	  - User
	security:
	  - Bearer: []
	parameters:
	  - in: body
	    name: username
	    description: New username
	    required: true
	    schema:
	      type: object
	      required:
	        - username
	      properties:
	        username:
	          type: string
	          example: newusername
	responses:
	  200:
	    description: Username updated successfully
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	  400:
	    description: Invalid input
	  401:
	    description: Unauthorized
	"""
	return User().update_username()

@user_blueprint.route("/password", methods=["POST"])
@token_required
def update_password():
	"""Update password
	---
	tags:
	  - User
	security:
	  - Bearer: []
	parameters:
	  - in: body
	    name: password
	    description: New password
	    required: true
	    schema:
	      type: object
	      required:
	        - old_password
	        - new_password
	      properties:
	        old_password:
	          type: string
	          example: oldpassword123
	        new_password:
	          type: string
	          example: newpassword123
	responses:
	  200:
	    description: Password updated successfully
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: success
	  400:
	    description: Invalid input or incorrect old password
	  401:
	    description: Unauthorized
	"""
	return User().update_password()