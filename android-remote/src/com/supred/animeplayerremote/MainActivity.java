package com.supred.animeplayerremote;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.KeyEvent;
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
 */
public class MainActivity extends Activity {
    private static final String PREFS = "remote";
    private static final String KEY_URL = "url";

    private WebView webView;
    private EditText urlInput;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        webView = findViewById(R.id.webView);
        urlInput = findViewById(R.id.urlInput);
        Button goButton = findViewById(R.id.goButton);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient());

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

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
