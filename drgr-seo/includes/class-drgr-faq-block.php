<?php
/**
 * DRGR_FAQ_Block — registers a simple Gutenberg FAQ block.
 *
 * The block renders an accessible FAQ list with a structured JSON-LD
 * FAQPage schema snippet for SEO.
 *
 * Usage: add the "DRGR FAQ" block in the Gutenberg editor, then enter
 * question/answer pairs in the block inspector sidebar.
 */

if ( ! defined( 'ABSPATH' ) ) exit;

class DRGR_FAQ_Block {

    public function __construct() {}

    /**
     * Register block type via block.json (dynamic render callback).
     * Called on the 'init' hook from DRGR_SEO_Manager.
     */
    public function register() {
        if ( ! function_exists( 'register_block_type' ) ) return;

        register_block_type( 'drgr-seo/faq', array(
            'editor_script'   => 'drgr-seo-faq-editor',
            'editor_style'    => 'drgr-seo-faq-editor-style',
            'style'           => 'drgr-seo-faq-style',
            'render_callback' => array( $this, 'render' ),
            'attributes'      => array(
                'items' => array(
                    'type'    => 'array',
                    'default' => array(),
                    'items'   => array(
                        'type'       => 'object',
                        'properties' => array(
                            'question' => array( 'type' => 'string', 'default' => '' ),
                            'answer'   => array( 'type' => 'string', 'default' => '' ),
                        ),
                    ),
                ),
                'title' => array(
                    'type'    => 'string',
                    'default' => 'FAQ',
                ),
            ),
        ) );

        $this->enqueue_block_assets();
    }

    /**
     * Register and enqueue block editor assets.
     */
    private function enqueue_block_assets() {
        // Editor script (inline JS — no build step required)
        wp_register_script(
            'drgr-seo-faq-editor',
            false,
            array( 'wp-blocks', 'wp-element', 'wp-editor', 'wp-components', 'wp-i18n' ),
            DRGR_SEO_VERSION,
            true
        );
        wp_add_inline_script( 'drgr-seo-faq-editor', $this->editor_script() );

        // Front-end style (inline)
        wp_register_style( 'drgr-seo-faq-style', false, array(), DRGR_SEO_VERSION );
        wp_add_inline_style( 'drgr-seo-faq-style', $this->frontend_css() );

        // Editor style (inline)
        wp_register_style( 'drgr-seo-faq-editor-style', false, array( 'wp-edit-blocks' ), DRGR_SEO_VERSION );
        wp_add_inline_style( 'drgr-seo-faq-editor-style', $this->editor_css() );
    }

    // ─── Render callback ─────────────────────────────────────────────────────

    /**
     * Server-side render callback.
     *
     * @param  array $attributes Block attributes.
     * @return string            HTML output.
     */
    public function render( $attributes ) {
        $items = isset( $attributes['items'] ) ? (array) $attributes['items'] : array();
        $title = isset( $attributes['title'] ) ? trim( $attributes['title'] ) : '';
        $items = array_filter( $items, static function( $item ) {
            return ! empty( $item['question'] ) || ! empty( $item['answer'] );
        } );

        if ( empty( $items ) ) return '';

        ob_start();
        ?>
        <div class="drgr-faq wp-block-drgr-seo-faq">
            <?php if ( $title !== '' ) : ?>
                <h2 class="drgr-faq__title"><?php echo esc_html( $title ); ?></h2>
            <?php endif; ?>

            <dl class="drgr-faq__list">
                <?php foreach ( $items as $item ) :
                    $q = isset( $item['question'] ) ? trim( $item['question'] ) : '';
                    $a = isset( $item['answer'] )   ? trim( $item['answer'] )   : '';
                    if ( $q === '' && $a === '' ) continue;
                    ?>
                    <div class="drgr-faq__item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
                        <dt class="drgr-faq__question" itemprop="name"><?php echo esc_html( $q ); ?></dt>
                        <dd class="drgr-faq__answer"
                            itemscope itemprop="acceptedAnswer"
                            itemtype="https://schema.org/Answer">
                            <span itemprop="text"><?php echo wp_kses_post( $a ); ?></span>
                        </dd>
                    </div>
                <?php endforeach; ?>
            </dl>

            <?php echo $this->json_ld( $items ); ?>
        </div>
        <?php
        return ob_get_clean();
    }

    // ─── JSON-LD ─────────────────────────────────────────────────────────────

    /**
     * Build a FAQPage JSON-LD script tag.
     *
     * @param  array $items
     * @return string
     */
    private function json_ld( array $items ) {
        $entities = array();
        foreach ( $items as $item ) {
            $q = isset( $item['question'] ) ? trim( $item['question'] ) : '';
            $a = isset( $item['answer'] )   ? trim( $item['answer'] )   : '';
            if ( $q === '' ) continue;
            $entities[] = array(
                '@type'          => 'Question',
                'name'           => $q,
                'acceptedAnswer' => array(
                    '@type' => 'Answer',
                    'text'  => wp_strip_all_tags( $a ),
                ),
            );
        }
        if ( empty( $entities ) ) return '';

        $schema = array(
            '@context'   => 'https://schema.org',
            '@type'      => 'FAQPage',
            'mainEntity' => $entities,
        );

        return '<script type="application/ld+json">'
            . wp_json_encode( $schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES )
            . "</script>\n";
    }

    // ─── Editor JS (no build step) ───────────────────────────────────────────

    /**
     * Inline Gutenberg block editor script.
     * Registered as a wp_add_inline_script so no separate JS file is needed.
     */
    private function editor_script() {
        return <<<'JS'
(function(blocks, element, blockEditor, components, i18n) {
    var el              = element.createElement;
    var Fragment        = element.Fragment;
    var InspectorControls = blockEditor.InspectorControls;
    var RichText        = blockEditor.RichText;
    var PanelBody       = components.PanelBody;
    var TextControl     = components.TextControl;
    var Button          = components.Button;
    var __              = i18n.__;

    blocks.registerBlockType('drgr-seo/faq', {
        title:    'DRGR FAQ',
        icon:     'editor-help',
        category: 'common',
        attributes: {
            items: { type: 'array',  default: [] },
            title: { type: 'string', default: 'FAQ' }
        },

        edit: function(props) {
            var attributes = props.attributes;
            var setAttributes = props.setAttributes;
            var items = attributes.items || [];

            function updateItem(index, field, value) {
                var newItems = items.slice();
                newItems[index] = Object.assign({}, newItems[index], { [field]: value });
                setAttributes({ items: newItems });
            }

            function addItem() {
                setAttributes({ items: items.concat([{ question: '', answer: '' }]) });
            }

            function removeItem(index) {
                setAttributes({ items: items.filter(function(_, i) { return i !== index; }) });
            }

            return el(Fragment, null,
                el(InspectorControls, null,
                    el(PanelBody, { title: __('FAQ Settings', 'drgr-seo'), initialOpen: true },
                        el(TextControl, {
                            label:    __('Block heading', 'drgr-seo'),
                            value:    attributes.title,
                            onChange: function(v) { setAttributes({ title: v }); }
                        }),
                        el(Button, {
                            isPrimary: true,
                            onClick:   addItem,
                            style:     { marginTop: '8px' }
                        }, __('+ Add item', 'drgr-seo'))
                    )
                ),
                el('div', { className: 'drgr-faq drgr-faq--editor' },
                    attributes.title
                        ? el('h2', { className: 'drgr-faq__title' }, attributes.title)
                        : null,
                    items.length === 0
                        ? el('p', { style: { color: '#999', fontStyle: 'italic' } },
                            __('No FAQ items yet. Add one in the sidebar.', 'drgr-seo'))
                        : items.map(function(item, index) {
                            return el('div', { key: index, className: 'drgr-faq__item drgr-faq__item--edit' },
                                el('div', { className: 'drgr-faq__item-header' },
                                    el('strong', null, '#' + (index + 1)),
                                    el(Button, {
                                        isDestructive: true,
                                        isSmall:       true,
                                        onClick:       function() { removeItem(index); },
                                        style:         { marginLeft: 'auto' }
                                    }, __('Remove', 'drgr-seo'))
                                ),
                                el(TextControl, {
                                    label:    __('Question', 'drgr-seo'),
                                    value:    item.question || '',
                                    onChange: function(v) { updateItem(index, 'question', v); }
                                }),
                                el(TextControl, {
                                    label:    __('Answer', 'drgr-seo'),
                                    value:    item.answer || '',
                                    onChange: function(v) { updateItem(index, 'answer', v); }
                                })
                            );
                        })
                )
            );
        },

        save: function() {
            return null; // server-side render
        }
    });
}(
    window.wp.blocks,
    window.wp.element,
    window.wp.blockEditor,
    window.wp.components,
    window.wp.i18n
));
JS;
    }

    // ─── CSS ─────────────────────────────────────────────────────────────────

    private function frontend_css() {
        return '
.drgr-faq { margin: 2em 0; }
.drgr-faq__title { margin-bottom: .75em; }
.drgr-faq__list { margin: 0; padding: 0; list-style: none; }
.drgr-faq__item { border-bottom: 1px solid #e0e0e0; margin-bottom: 0; }
.drgr-faq__item:first-child { border-top: 1px solid #e0e0e0; }
.drgr-faq__question {
    font-weight: 600;
    padding: .85em 0 .4em;
    cursor: pointer;
    display: block;
}
.drgr-faq__answer {
    margin: 0;
    padding: 0 0 .85em;
    line-height: 1.6;
}
';
    }

    private function editor_css() {
        return '
.drgr-faq--editor .drgr-faq__item--edit {
    border: 1px dashed #c8d8e8;
    padding: 8px 12px;
    margin-bottom: 12px;
    border-radius: 4px;
    background: #f9fbfd;
}
.drgr-faq--editor .drgr-faq__item-header {
    display: flex;
    align-items: center;
    margin-bottom: 6px;
}
';
    }
}
