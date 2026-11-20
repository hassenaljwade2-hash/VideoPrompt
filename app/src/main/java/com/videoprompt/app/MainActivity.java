package com.videoprompt.app;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

public class MainActivity extends Activity {

    private static final int PICK_FILE = 1001;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // الشاشة تبقى شغالة أثناء المعالجة
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true); // يسمح بالاتصال بالـ API من الصفحة المحلية
        s.setMediaPlaybackRequiresUserGesture(false);

        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("video/*");
                i.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"video/*", "audio/*"});
                try {
                    startActivityForResult(Intent.createChooser(i, "اختار فيديو"), PICK_FILE);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        web.addJavascriptInterface(new Bridge(), "Android");
        web.loadUrl("file:///android_asset/index.html");
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == PICK_FILE && fileCallback != null) {
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                result = new Uri[]{data.getData()};
            }
            fileCallback.onReceiveValue(result);
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    /** جسر بين الصفحة والأندرويد: حفظ الملفات بمجلد التنزيلات + النسخ */
    private class Bridge {
        private OutputStream out;
        private String savedPath;

        @JavascriptInterface
        public void beginFile(String name, String mime) throws Exception {
            closeQuietly();
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                v.put(MediaStore.Downloads.MIME_TYPE, mime);
                v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/VideoPrompt");
                ContentResolver cr = getContentResolver();
                Uri uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new Exception("ما كدرت أسوي الملف");
                out = cr.openOutputStream(uri);
                savedPath = "Download/VideoPrompt/" + name;
            } else {
                File dir = new File(Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS), "VideoPrompt");
                if (!dir.exists() && !dir.mkdirs()) {
                    dir = getExternalFilesDir(null);
                }
                File f = new File(dir, name);
                out = new FileOutputStream(f);
                savedPath = f.getAbsolutePath();
            }
        }

        @JavascriptInterface
        public void appendChunk(String b64) throws Exception {
            if (out == null) throw new Exception("الملف مو مفتوح");
            out.write(Base64.decode(b64, Base64.DEFAULT));
        }

        @JavascriptInterface
        public String endFile() throws Exception {
            if (out != null) { out.flush(); out.close(); out = null; }
            return savedPath;
        }

        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("prompt", text));
        }

        private void closeQuietly() {
            try { if (out != null) out.close(); } catch (Exception ignored) { }
            out = null;
        }
    }
}
