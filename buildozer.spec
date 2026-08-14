[app]

# (str) Title of your application
title = ChromaBeam

# (str) Package name
package.name = chromabeam

# (str) Package domain (needed for android/ios packaging)
package.domain = org.henry.chromabeam

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,html,js,css,json

# (str) Icon of the application
icon.filename = %(source.dir)s/assets/icon.png

# (str) Presplash of the application
presplash.filename = %(source.dir)s/assets/icon.png

# (str) Application versioning
version = 1.0.0

# (int) 32-bit safe numeric version (Learned Invariant to prevent Gradle integer overflow)
android.numeric_version = 2680317

# (list) Application requirements
requirements = python3,kivy,opencv,numpy,requests,android,pillow,qrcode

# (list) Permissions
android.permissions = CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,INTERNET,ACCESS_NETWORK_STATE

# (int) Target Android API
android.api = 33

# (int) Minimum API supported
android.minapi = 24

# (int) Android SDK version to use
android.sdk = 33

# (str) Android NDK version to use
android.ndk = 25b

# (bool) Use --private data storage (True) or --dir public storage (False)
android.private_storage = True

# (list) Supported orientations
orientation = portrait,landscape

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
