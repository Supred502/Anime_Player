package com.supred.animeplayerremote;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;

/**
 * A thin WebView shell around Anime Player's own phone remote page (see
 * animeplayer/remote/server.py) -- all the actual remote control UI and
 * logic lives in that server-rendered page, not here. This app exists only
 * to give it a home-screen icon and remember the PC's address between
 * launches, since the LAN IP/port can change and there's no bundled way to
 * discover it automatically (matches the "no need for fancy stuff" scope of
 * the pairing model itself).
 *
 * The page talks to it through `AnimePlayerApp` (see Bridge): it asks this
 * app's version, to offer the newer one the PC carries, and hands over the
 * PC's accent colour, so the bar here matches the app it's connected to.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "remote";
    private static final String KEY_URL = "url";
    private static final String KEY_ACCENT = "accent";

    private WebView webView;
    private EditText urlInput;
    private Button goButton;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        webView = findViewById(R.id.webView);
        urlInput = findViewById(R.id.urlInput);
        goButton = findViewById(R.id.goButton);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.addJavascriptInterface(new Bridge(), "AnimePlayerApp");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // Only the page itself failing, not an image or a poll.
                if (request.isForMainFrame()) showUnreachable();
            }
        });
        // Anything the page hands off to download (the app update) goes to
        // the browser, which knows how to save and install an APK; a WebView
        // on its own silently does nothing with a download.
        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, length) -> openInBrowser(url));

        applyAccent(prefs.getString(KEY_ACCENT, "#4c8bf5"));

        String savedUrl = prefs.getString(KEY_URL, "");
        urlInput.setText(savedUrl);
        if (!savedUrl.isEmpty()) {
            webView.loadUrl(savedUrl);
        }

        goButton.setOnClickListener(v -> connect());
        urlInput.setOnEditorActionListener((v, actionId, event) -> {
            connect();
            return true;
        });
    }

    private void connect() {
        String url = urlInput.getText().toString().trim();
        if (url.isEmpty()) return;
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        prefs.edit().putString(KEY_URL, url).apply();
        webView.loadUrl(url);
    }

    private void showUnreachable() {
        String html = "<html><body style='background:#1d1d1f;color:#f0f0f0;font-family:sans-serif;"
                + "padding:24px;text-align:center'><h3>Can't reach the PC</h3>"
                + "<p style='opacity:.75'>Is Anime Player open on it, with the phone remote on, "
                + "and is this phone on the same Wi-Fi? The address is under Settings &rarr; Phone remote.</p>"
                + "<p style='opacity:.75'>Then tap Connect again.</p></body></html>";
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void openInBrowser(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
            // No browser at all: nothing more this app can do.
        }
    }

    /** The accent on this app's own parts: the Connect button and the bars. */
    private void applyAccent(String hex) {
        int color;
        try {
            color = Color.parseColor(hex);
        } catch (IllegalArgumentException e) {
            return;
        }
        GradientDrawable button = new GradientDrawable();
        button.setColor(color);
        button.setCornerRadius(12 * getResources().getDisplayMetrics().density);
        goButton.setBackground(button);
        int dark = Color.rgb(Color.red(color) / 3, Color.green(color) / 3, Color.blue(color) / 3);
        getWindow().setStatusBarColor(dark);
        getWindow().setNavigationBarColor(Color.parseColor("#1d1d1f"));
    }

    /** What the remote page may ask of this app (window.AnimePlayerApp). */
    private class Bridge {
        @JavascriptInterface
        public int version() {
            try {
                PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
                return info.versionCode;
            } catch (Exception e) {
                return 0;
            }
        }

        @JavascriptInterface
        public void setTheme(String accent) {
            prefs.edit().putString(KEY_ACCENT, accent).apply();
            runOnUiThread(() -> applyAccent(accent));
        }

        @JavascriptInterface
        public void openExternal(String url) {
            runOnUiThread(() -> openInBrowser(url));
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
