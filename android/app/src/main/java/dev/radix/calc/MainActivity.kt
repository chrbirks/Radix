package dev.radix.calc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.Text
import androidx.compose.runtime.remember

// Scaffold placeholder: proves the Chaquopy round-trip end to end. The real
// calculator screen replaces this in the UI tasks.
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val version = remember {
                ChaquopyBridge(filesDir.path, null).call("version", "{}")
            }
            Text("Radix $version")
        }
    }
}
