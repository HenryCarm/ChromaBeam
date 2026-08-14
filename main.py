"""
QR ChromaBeam — Mobile & Desktop Unified Entrypoint
On Android: Launches hardware-accelerated full-screen Native WebView with camera & worker pipeline.
On Desktop: Launches PyQt6 Desktop Studio.
"""

import os
import sys

# Desktop Launch Path
if 'ANDROID_ARGUMENT' not in os.environ and 'ANDROID_PRIVATE' not in os.environ:
    try:
        from desktop_app import main
        if __name__ == '__main__':
            main()
            sys.exit(0)
    except ImportError:
        pass

# Android Kivy Entrypoint
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import mainthread
from kivy.utils import platform

class QRChromaBeamApp(App):
    def build(self):
        self.title = "QR ChromaBeam"
        layout = BoxLayout(orientation='vertical')
        return layout

    def on_start(self):
        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.CAMERA,
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.MANAGE_EXTERNAL_STORAGE
            ], self._on_permissions_result)
        else:
            self._setup_view()

    def _on_permissions_result(self, permissions, grant_results):
        self._setup_view()

    @mainthread
    def _setup_view(self):
        if platform == 'android':
            try:
                from jnius import autoclass, PythonJavaClass, java_method
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                WebView = autoclass('android.webkit.WebView')
                WebSettings = autoclass('android.webkit.WebSettings')
                WebViewClient = autoclass('android.webkit.WebViewClient')
                
                class ChromeClient(PythonJavaClass):
                    __javainterfaces__ = ['android/webkit/WebChromeClient']
                    __javacontext__ = 'app'
                    
                    @java_method('(Landroid/webkit/PermissionRequest;)V')
                    def onPermissionRequest(self, request):
                        try:
                            request.grant(request.getResources())
                        except Exception as ex:
                            print(f"[ChromeClient] Permission grant error: {ex}")

                activity = PythonActivity.mActivity
                webview = WebView(activity)
                settings = webview.getSettings()
                settings.setJavaScriptEnabled(True)
                settings.setDomStorageEnabled(True)
                settings.setAllowFileAccess(True)
                settings.setAllowContentAccess(True)
                settings.setAllowFileAccessFromFileURLs(True)
                settings.setAllowUniversalAccessFromFileURLs(True)
                settings.setMediaPlaybackRequiresUserGesture(False)
                
                webview.setWebViewClient(WebViewClient())
                webview.setWebChromeClient(ChromeClient())

                app_dir = activity.getFilesDir().getAbsolutePath() + "/app"
                html_path = os.path.join(app_dir, "chromabeam_offline.html")
                if os.path.exists(html_path):
                    webview.loadUrl(f"file://{html_path}")
                else:
                    webview.loadUrl("file:///android_asset/chromabeam_offline.html")

                activity.setContentView(webview)
            except Exception as e:
                print(f"[QR ChromaBeam] Android WebView error: {e}")

if __name__ == '__main__':
    QRChromaBeamApp().run()
