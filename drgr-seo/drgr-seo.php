<?php
/**
 * Plugin Name: DRGR SEO
 * Plugin URI:  https://drgr.ru
 * Description: Advanced SEO management with Yoast %%variable%% support, OG/Twitter-X meta variations, FAQ block and license management. Supports all public post types.
 * Version:     1.0.0
 * Author:      DRGR
 * License:     GPL-2.0+
 * Text Domain: drgr-seo
 * Requires at least: 5.8
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) exit;

define( 'DRGR_SEO_VERSION',     '1.0.0' );
define( 'DRGR_SEO_PLUGIN_FILE', __FILE__ );
define( 'DRGR_SEO_PLUGIN_DIR',  plugin_dir_path( __FILE__ ) );
define( 'DRGR_SEO_PLUGIN_URL',  plugin_dir_url( __FILE__ ) );

class DRGR_SEO_Manager {

    /** @var DRGR_License_Manager */
    private $license_manager;

    public function __construct() {
        $this->load_dependencies();
        $this->license_manager = new DRGR_License_Manager();

        add_action( 'wp_head',               array( $this, 'output_meta_tags' ), 1 );
        add_action( 'add_meta_boxes',        array( $this, 'add_meta_boxes' ) );
        add_action( 'save_post',             array( $this, 'save_meta_data' ) );
        add_action( 'admin_menu',            array( $this, 'add_admin_menu' ) );
        add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_admin_assets' ) );
        add_action( 'init',                  array( $this, 'register_faq_block' ) );

        // Remove Yoast head for force-override post types / per-post toggle
        add_action( 'template_redirect', array( $this, 'maybe_remove_yoast_head' ) );

        // Hide Yoast meta box priority (de-prioritise) when disabled per post
        add_filter( 'wpseo_metabox_prio', array( $this, 'maybe_disable_yoast_metabox' ) );
    }

    // ─── Dependencies ────────────────────────────────────────────────────────

    private function load_dependencies() {
        require_once DRGR_SEO_PLUGIN_DIR . 'includes/class-drgr-license.php';
        require_once DRGR_SEO_PLUGIN_DIR . 'includes/class-drgr-meta-replacer.php';
        require_once DRGR_SEO_PLUGIN_DIR . 'includes/class-drgr-faq-block.php';
    }

    // ─── Assets ──────────────────────────────────────────────────────────────

    public function enqueue_admin_assets( $hook ) {
        wp_enqueue_style(
            'drgr-seo-admin',
            DRGR_SEO_PLUGIN_URL . 'assets/admin.css',
            array(),
            DRGR_SEO_VERSION
        );
    }

    // ─── Admin menu / settings page ─────────────────────────────────────────

    public function add_admin_menu() {
        add_options_page(
            'DRGR SEO Settings',
            'DRGR SEO',
            'manage_options',
            'drgr-seo-settings',
            array( $this, 'admin_page' )
        );
    }

    public function admin_page() {
        if ( ! current_user_can( 'manage_options' ) ) return;

        $saved_notice = '';
        if (
            isset( $_POST['drgr_seo_settings_nonce'] ) &&
            wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['drgr_seo_settings_nonce'] ) ), 'drgr_seo_settings' )
        ) {
            $this->save_settings();
            $saved_notice = '<div class="notice notice-success"><p>' . esc_html__( 'Settings saved.', 'drgr-seo' ) . '</p></div>';
        }

        $settings   = $this->get_settings();
        $post_types = $this->get_supported_post_types();
        ?>
        <div class="wrap drgr-seo-admin">
            <h1><?php esc_html_e( 'DRGR SEO Settings', 'drgr-seo' ); ?></h1>
            <?php echo $saved_notice; // already escaped above ?>

            <h2 class="nav-tab-wrapper">
                <a href="#drgr-tab-license"   class="nav-tab nav-tab-active" data-tab="drgr-tab-license"><?php esc_html_e( 'License', 'drgr-seo' ); ?></a>
                <a href="#drgr-tab-templates" class="nav-tab" data-tab="drgr-tab-templates"><?php esc_html_e( 'Meta Templates', 'drgr-seo' ); ?></a>
                <a href="#drgr-tab-yoast"     class="nav-tab" data-tab="drgr-tab-yoast"><?php esc_html_e( 'Yoast Integration', 'drgr-seo' ); ?></a>
            </h2>

            <!-- ── LICENSE ── -->
            <div id="drgr-tab-license" class="drgr-tab-content">
                <?php $this->license_manager->license_interface(); ?>
            </div>

            <!-- ── TEMPLATES ── -->
            <div id="drgr-tab-templates" class="drgr-tab-content" style="display:none">
                <p class="description">
                    <?php esc_html_e( 'Supported Yoast variables:', 'drgr-seo' ); ?>
                    <code>%%title%% %%sitename%% %%sitedesc%% %%sep%% %%description%% %%excerpt%% %%category%% %%date%% %%modified%% %%currentyear%% %%currentmonth%% %%currentday%% %%permalink%% %%id%% %%name%%</code>
                </p>
                <form method="post">
                    <?php wp_nonce_field( 'drgr_seo_settings', 'drgr_seo_settings_nonce' ); ?>
                    <?php foreach ( $post_types as $pt ) :
                        $pt_obj   = get_post_type_object( $pt );
                        $pt_label = $pt_obj ? $pt_obj->labels->name : $pt;
                        $tmpl     = isset( $settings['templates'][ $pt ] ) ? $settings['templates'][ $pt ] : array();
                        $def      = $this->default_templates();
                    ?>
                    <div class="drgr-pt-section">
                        <h4><?php echo esc_html( $pt_label ); ?> &mdash; <code><?php echo esc_html( $pt ); ?></code></h4>
                        <table class="form-table drgr-templates-table">
                            <?php foreach ( $this->template_fields() as $field_key => $field_label ) :
                                $val = isset( $tmpl[ $field_key ] ) ? $tmpl[ $field_key ] : $def[ $field_key ];
                            ?>
                            <tr>
                                <th scope="row"><label><?php echo esc_html( $field_label ); ?></label></th>
                                <td>
                                    <?php if ( strpos( $field_key, 'description' ) !== false ) : ?>
                                    <textarea name="templates[<?php echo esc_attr( $pt ); ?>][<?php echo esc_attr( $field_key ); ?>]"
                                              class="large-text" rows="2"><?php echo esc_textarea( $val ); ?></textarea>
                                    <?php else : ?>
                                    <input type="text"
                                           name="templates[<?php echo esc_attr( $pt ); ?>][<?php echo esc_attr( $field_key ); ?>]"
                                           value="<?php echo esc_attr( $val ); ?>"
                                           class="large-text">
                                    <?php endif; ?>
                                </td>
                            </tr>
                            <?php endforeach; ?>
                        </table>
                    </div>
                    <?php endforeach; ?>
                    <?php submit_button( __( 'Save Templates', 'drgr-seo' ) ); ?>
                </form>
            </div>

            <!-- ── YOAST INTEGRATION ── -->
            <div id="drgr-tab-yoast" class="drgr-tab-content" style="display:none">
                <p class="description">
                    <?php esc_html_e( 'Select post types where DRGR SEO forcibly removes Yoast meta tags from <head> and replaces them with its own.', 'drgr-seo' ); ?>
                </p>
                <form method="post">
                    <?php wp_nonce_field( 'drgr_seo_settings', 'drgr_seo_settings_nonce' ); ?>
                    <table class="form-table">
                        <?php foreach ( $post_types as $pt ) :
                            $pt_obj   = get_post_type_object( $pt );
                            $pt_label = $pt_obj ? $pt_obj->labels->name : $pt;
                            $checked  = ! empty( $settings['force_override'][ $pt ] );
                        ?>
                        <tr>
                            <th scope="row"><?php echo esc_html( $pt_label ); ?> (<code><?php echo esc_html( $pt ); ?></code>)</th>
                            <td>
                                <input type="checkbox"
                                       name="force_override[<?php echo esc_attr( $pt ); ?>]"
                                       value="1"
                                       <?php checked( $checked ); ?>>
                                <?php esc_html_e( 'Override Yoast for this post type', 'drgr-seo' ); ?>
                            </td>
                        </tr>
                        <?php endforeach; ?>
                    </table>
                    <?php submit_button( __( 'Save Yoast Settings', 'drgr-seo' ) ); ?>
                </form>
            </div>
        </div>

        <script>
        (function($) {
            $('.nav-tab').on('click', function(e) {
                e.preventDefault();
                var tab = $(this).data('tab');
                $('.nav-tab').removeClass('nav-tab-active');
                $(this).addClass('nav-tab-active');
                $('.drgr-tab-content').hide();
                $('#' + tab).show();
            });
        })(jQuery);
        </script>
        <?php
    }

    private function template_fields() {
        return array(
            'seo_title'       => __( 'SEO Title', 'drgr-seo' ),
            'seo_description' => __( 'SEO Description', 'drgr-seo' ),
            'og_title'        => __( 'OG Title', 'drgr-seo' ),
            'og_description'  => __( 'OG Description', 'drgr-seo' ),
            'tw_title'        => __( 'Twitter/X Title', 'drgr-seo' ),
            'tw_description'  => __( 'Twitter/X Description', 'drgr-seo' ),
        );
    }

    private function default_templates() {
        return array(
            'seo_title'       => '%%title%% %%sep%% %%sitename%%',
            'seo_description' => '%%description%%',
            'og_title'        => '%%title%% %%sep%% %%sitename%%',
            'og_description'  => '%%description%%',
            'tw_title'        => '%%title%% %%sep%% %%sitename%%',
            'tw_description'  => '%%description%%',
        );
    }

    private function save_settings() {
        $settings = $this->get_settings();

        // Templates — sanitize each value
        if ( isset( $_POST['templates'] ) && is_array( $_POST['templates'] ) ) {
            $clean = array();
            foreach ( $_POST['templates'] as $pt => $fields ) {
                $pt = sanitize_key( $pt );
                if ( is_array( $fields ) ) {
                    foreach ( $fields as $k => $v ) {
                        $clean[ $pt ][ sanitize_key( $k ) ] = sanitize_textarea_field( wp_unslash( $v ) );
                    }
                }
            }
            $settings['templates'] = $clean;
        }

        // Force-override post types
        $settings['force_override'] = array();
        if ( isset( $_POST['force_override'] ) && is_array( $_POST['force_override'] ) ) {
            foreach ( $_POST['force_override'] as $pt => $v ) {
                $settings['force_override'][ sanitize_key( $pt ) ] = 1;
            }
        }

        update_option( 'drgr_seo_settings', $settings );
    }

    public function get_settings() {
        return wp_parse_args(
            get_option( 'drgr_seo_settings', array() ),
            array( 'templates' => array(), 'force_override' => array() )
        );
    }

    // ─── FAQ Block ───────────────────────────────────────────────────────────

    public function register_faq_block() {
        $block = new DRGR_FAQ_Block();
        $block->register();
    }

    // ─── Meta boxes (all public post types) ──────────────────────────────────

    public function add_meta_boxes() {
        foreach ( $this->get_supported_post_types() as $post_type ) {
            add_meta_box(
                'drgr_seo_meta',
                __( 'DRGR SEO', 'drgr-seo' ),
                array( $this, 'meta_box_callback' ),
                $post_type,
                'normal',
                'high'
            );
        }
    }

    public function meta_box_callback( $post ) {
        wp_nonce_field( 'drgr_seo_nonce', 'drgr_seo_nonce' );

        // Direct overrides
        $seo_title    = get_post_meta( $post->ID, '_drgr_seo_title',       true );
        $seo_desc     = get_post_meta( $post->ID, '_drgr_seo_description', true );
        $og_title     = get_post_meta( $post->ID, '_drgr_og_title',        true );
        $og_desc      = get_post_meta( $post->ID, '_drgr_og_description',  true );
        $tw_title     = get_post_meta( $post->ID, '_drgr_tw_title',        true );
        $tw_desc      = get_post_meta( $post->ID, '_drgr_tw_description',  true );
        $disable_yoast = get_post_meta( $post->ID, '_drgr_disable_yoast', true );

        // Variations
        $var_meta = array(
            'seo_title' => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_seo_title_variations', true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_title_var', true ),
            ),
            'seo_desc'  => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_seo_desc_variations',  true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_desc_var', true ),
            ),
            'og_title'  => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_og_title_variations',  true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_og_title_var', true ),
            ),
            'og_desc'   => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_og_desc_variations',   true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_og_desc_var', true ),
            ),
            'tw_title'  => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_tw_title_variations',  true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_tw_title_var', true ),
            ),
            'tw_desc'   => array(
                'vars'   => get_post_meta( $post->ID, '_drgr_tw_desc_variations',   true ) ?: array( '' ),
                'active' => (int) get_post_meta( $post->ID, '_drgr_active_tw_desc_var', true ),
            ),
        );

        include DRGR_SEO_PLUGIN_DIR . 'includes/meta-box-template.php';
    }

    // ─── Save post meta ──────────────────────────────────────────────────────

    public function save_meta_data( $post_id ) {
        if (
            ! isset( $_POST['drgr_seo_nonce'] ) ||
            ! wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['drgr_seo_nonce'] ) ), 'drgr_seo_nonce' )
        ) return;
        if ( defined( 'DOING_AUTOSAVE' ) && DOING_AUTOSAVE ) return;
        if ( ! current_user_can( 'edit_post', $post_id ) ) return;

        // Simple text overrides
        $text_fields = array(
            '_drgr_seo_title'       => 'drgr_seo_title',
            '_drgr_seo_description' => 'drgr_seo_description',
            '_drgr_og_title'        => 'drgr_og_title',
            '_drgr_og_description'  => 'drgr_og_description',
            '_drgr_tw_title'        => 'drgr_tw_title',
            '_drgr_tw_description'  => 'drgr_tw_description',
        );
        foreach ( $text_fields as $meta_key => $post_key ) {
            $value = isset( $_POST[ $post_key ] ) ? sanitize_textarea_field( wp_unslash( $_POST[ $post_key ] ) ) : '';
            update_post_meta( $post_id, $meta_key, $value );
        }

        update_post_meta( $post_id, '_drgr_disable_yoast', isset( $_POST['drgr_disable_yoast'] ) ? '1' : '' );

        // Variations arrays
        $var_fields = array(
            '_drgr_seo_title_variations' => 'drgr_seo_title_variations',
            '_drgr_seo_desc_variations'  => 'drgr_seo_desc_variations',
            '_drgr_og_title_variations'  => 'drgr_og_title_variations',
            '_drgr_og_desc_variations'   => 'drgr_og_desc_variations',
            '_drgr_tw_title_variations'  => 'drgr_tw_title_variations',
            '_drgr_tw_desc_variations'   => 'drgr_tw_desc_variations',
        );
        foreach ( $var_fields as $meta_key => $post_key ) {
            $vars = isset( $_POST[ $post_key ] ) && is_array( $_POST[ $post_key ] )
                ? array_map( 'sanitize_textarea_field', array_map( 'wp_unslash', $_POST[ $post_key ] ) )
                : array();
            update_post_meta( $post_id, $meta_key, $vars );
        }

        // Active variation indices
        $active_fields = array(
            '_drgr_active_title_var'    => 'drgr_active_title_var',
            '_drgr_active_desc_var'     => 'drgr_active_desc_var',
            '_drgr_active_og_title_var' => 'drgr_active_og_title_var',
            '_drgr_active_og_desc_var'  => 'drgr_active_og_desc_var',
            '_drgr_active_tw_title_var' => 'drgr_active_tw_title_var',
            '_drgr_active_tw_desc_var'  => 'drgr_active_tw_desc_var',
        );
        foreach ( $active_fields as $meta_key => $post_key ) {
            update_post_meta( $post_id, $meta_key, isset( $_POST[ $post_key ] ) ? (int) $_POST[ $post_key ] : 0 );
        }
    }

    // ─── Yoast override ──────────────────────────────────────────────────────

    /**
     * Called on template_redirect — removes Yoast's wp_head output when needed.
     */
    public function maybe_remove_yoast_head() {
        if ( ! is_singular() ) return;

        $post      = get_queried_object();
        $post_type = get_post_type( $post );
        $settings  = $this->get_settings();

        $force   = ! empty( $settings['force_override'][ $post_type ] );
        $per_post = (bool) get_post_meta( $post->ID, '_drgr_disable_yoast', true );

        if ( $force || $per_post ) {
            $this->remove_yoast_output();
        }
    }

    /**
     * Removes Yoast SEO meta output from wp_head (compatible with Yoast 14–22+).
     */
    private function remove_yoast_output() {
        global $wp_filter;

        // Yoast 14+ uses wpseo_head action
        if ( isset( $wp_filter['wpseo_head'] ) ) {
            remove_all_actions( 'wpseo_head' );
        }

        // Remove the hook that triggers wpseo_head
        remove_action( 'wp_head', 'wpseo_head', 1 );

        // Legacy: WPSEO_Frontend (Yoast < 14)
        if ( class_exists( 'WPSEO_Frontend' ) ) {
            remove_action( 'wp_head', array( WPSEO_Frontend::get_instance(), 'head' ), 1 );
        }

        // Fallback: remove all Yoast meta filters so nothing leaks through
        foreach ( array( 'wpseo_title', 'wpseo_metadesc', 'wpseo_canonical', 'wpseo_robots' ) as $filter ) {
            if ( has_filter( $filter ) ) {
                remove_all_filters( $filter );
            }
        }
    }

    /**
     * Lowers Yoast meta-box priority to 'low' when per-post disable is checked.
     * This keeps the Yoast meta box but pushes it below DRGR SEO.
     */
    public function maybe_disable_yoast_metabox( $priority ) {
        if ( ! is_admin() ) return $priority;

        // Use the global $post object which WordPress sets reliably on edit screens —
        // avoids direct $_GET access and is safe in all admin contexts.
        $post_id = 0;
        if ( ! empty( $GLOBALS['post'] ) && $GLOBALS['post'] instanceof WP_Post ) {
            $post_id = $GLOBALS['post']->ID;
        } elseif ( isset( $_GET['post'] ) ) {
            // Fallback: cast to int prevents any injection; no user-facing output here.
            $post_id = (int) $_GET['post'];
        }

        if ( $post_id && get_post_meta( $post_id, '_drgr_disable_yoast', true ) ) {
            return 'low';
        }
        return $priority;
    }

    // ─── Output meta tags ────────────────────────────────────────────────────

    public function output_meta_tags() {
        if ( ! $this->license_manager->is_license_valid() ) return;
        if ( ! is_singular() ) return;

        $post = get_queried_object();
        if ( ! $post instanceof WP_Post ) return;

        $replacer = new DRGR_Meta_Replacer( $this->get_settings() );
        $replacer->output_meta_tags( $post->ID );
    }

    // ─── Helpers ─────────────────────────────────────────────────────────────

    /**
     * Returns all public post type slugs (built-in + custom), refreshed dynamically.
     */
    public function get_supported_post_types() {
        return array_values( get_post_types( array( 'public' => true ), 'names' ) );
    }
}

// ── Bootstrap ────────────────────────────────────────────────────────────────

new DRGR_SEO_Manager();

register_activation_hook( __FILE__, 'drgr_seo_activate' );
register_deactivation_hook( __FILE__, 'drgr_seo_deactivate' );

function drgr_seo_activate() {
    // Flush rewrite rules on activation in case post types need them.
    flush_rewrite_rules();
}

function drgr_seo_deactivate() {
    // Nothing to clean up on deactivation.
}
