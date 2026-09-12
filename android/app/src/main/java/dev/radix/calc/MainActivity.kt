package dev.radix.calc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dev.radix.calc.ui.CalculatorScreen
import dev.radix.calc.ui.RadixTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import java.io.File

class MainActivity : ComponentActivity() {
    @OptIn(ExperimentalCoroutinesApi::class)
    private val vm: CalculatorViewModel by viewModels {
        viewModelFactory {
            initializer {
                // Variables, ans, modes and the MRU list; history has its own JSONL.
                val stateFile = File(filesDir, "state.json")
                val bridge = ChaquopyBridge(filesDir.path, stateFile.takeIf { it.exists() }?.readText())
                CalculatorViewModel(
                    client = RadixClient(bridge),
                    // One thread: the Python Session is never touched concurrently.
                    bridgeDispatcher = Dispatchers.IO.limitedParallelism(1),
                    persist = { stateFile.writeText(it) },
                )
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { RadixTheme { CalculatorScreen(vm) } }
    }

    override fun onStop() {
        super.onStop()
        vm.save()
    }
}
